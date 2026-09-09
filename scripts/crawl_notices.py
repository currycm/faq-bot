"""
南京工业职业技术大学四部门通知爬虫（公开页面，遵守 robots 与频率控制）

覆盖站点：
  教务处    https://jwc.niit.edu.cn
  学工处    https://xsc.niit.edu.cn
  数智化处  https://xxh.niit.edu.cn
  后勤      https://hqglc.niit.edu.cn

栏目入口在 LIST_PAGES 里维护；输出到 data/crawled/<site>_<category>.json。

每条记录包含：id, site, source, category, url, title, date, content。

用法：
    python scripts/crawl_notices.py                  # 全量
    python scripts/crawl_notices.py --site jwc       # 单站点
    python scripts/crawl_notices.py --max-pages 3    # 每栏目最多翻 3 页
    python scripts/crawl_notices.py --delay 1.5      # 请求间隔秒数（默认 1.5）

实现说明：
  - 站群页面是某高校自研系统，详情页正文通常在 div.v_news_content；
    标题在 <h1 class="v_news_title"> 或 <h1>，日期在 span.date 或正文前后。
  - 本爬虫**只抓公开页面**，遇登录墙、动态加载（JS 渲染）会跳过并打印原因。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "data" / "crawled"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# 列表页（绝对地址）+ 栏目中文名 + 来源部门
LIST_PAGES: list[tuple[str, str, str]] = [
    # 教务处
    ("https://jwc.niit.edu.cn/2370/list.htm",          "通知公告", "教务处"),
    ("https://jwc.niit.edu.cn/2369/list.htm",          "教学动态", "教务处"),

    # 学工处
    ("https://xsc.niit.edu.cn/3818/list.htm",          "通知公告", "学工处"),
    ("https://xsc.niit.edu.cn/gygl1/list.htm",         "公寓管理", "学工处"),
    ("https://xsc.niit.edu.cn/jlpy/list.htm",          "奖励评优", "学工处"),

    # 数智化处
    ("https://xxh.niit.edu.cn/2265/list.htm",          "通知公告", "数智化处"),

    # 后勤
    # 后勤通知公告栏目页 4910 报"找不到对应的栏目"，暂留空
]


# ---------------------------------------------------------------- HTML 解析
class ListPageParser(HTMLParser):
    """从列表页提取文章链接 + 标题 + 日期。

    学校站群列表项大致结构：
      <li><a href="...page.htm">标题</a><span>YYYY-MM-DD</span></li>
    不同栏目微差，这里宽松匹配。
    """

    def __init__(self, base_url: str):
        super().__init__()
        self.base = base_url
        self.items: list[dict] = []     # {url, title, date}
        self._in_a = False
        self._current_href: str | None = None
        self._current_text: list[str] = []
        self._after_link_buf: list[str] = []  # 链接之后的日期文本
        self._state = "idle"            # idle | in_a | after_a

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href and "page.htm" in href:
                self._in_a = True
                self._current_href = href
                self._current_text = []
                self._after_link_buf = []
                self._state = "in_a"

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._state == "in_a":
            self._state = "after_a"

    def handle_data(self, data: str) -> None:
        if self._state == "in_a":
            self._current_text.append(data)
        elif self._state == "after_a":
            self._after_link_buf.append(data)

    def close(self) -> None:                     # type: ignore[override]
        super().close()
        for href in [self._current_href] if self._current_href else []:
            url = urllib.parse.urljoin(self.base, href) if href else None
            if not url:
                continue
            title = re.sub(r"\s+", " ", "".join(self._current_text)).strip()
            date_text = re.sub(r"\s+", "", "".join(self._after_link_buf)).strip()
            date_match = re.search(r"(\d{4}[-/]?\d{2}[-/]?\d{2})", date_text) \
                or re.search(r"(\d{4}[-/]?\d{2}[-/]?\d{2})", title)
            date = date_match.group(1).replace("/", "-") if date_match else ""
            if title:
                self.items.append({"url": url, "title": title, "date": date})


class DetailPageParser(HTMLParser):
    """从详情页提取正文。

    站群结构通常是 <h1 class="v_news_title">...</h1>
    和 <div class="v_news_content">...</div>。两个都找不到时回退到 <article>/<main>。
    """

    def __init__(self):
        super().__init__()
        self.in_title = False
        self.in_content = False
        self.in_skip = False
        self.title_parts: list[str] = []
        self.content_parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        classes = (a.get("class") or "").lower()
        style = (a.get("style") or "").lower()
        if tag == "h1" and ("v_news_title" in classes or "title" in classes):
            self.in_title = True
        elif tag == "div" and "v_news_content" in classes:
            self.in_content = True
        elif tag == "script" or tag == "style" or "display:none" in style:
            self.in_skip = True
            self.skip_depth = 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1" and self.in_title:
            self.in_title = False
        elif tag == "div" and self.in_content:
            self.in_content = False
        elif self.in_skip:
            self.skip_depth -= 1
            if self.skip_depth <= 0:
                self.in_skip = False
                self.skip_depth = 0

    def handle_data(self, data: str) -> None:
        if self.in_skip:
            return
        if self.in_title:
            self.title_parts.append(data)
        elif self.in_content:
            self.content_parts.append(data)

    @property
    def title(self) -> str:
        return re.sub(r"\s+", " ", "".join(self.title_parts)).strip()

    @property
    def content(self) -> str:
        text = "".join(self.content_parts)
        text = re.sub(r"[\t ]+", " ", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


# ---------------------------------------------------------------- 网络
import urllib.parse


def http_get(url: str, timeout: float = 15.0) -> tuple[str, str]:
    """GET 一个 URL，返回 (html, encoding)。失败抛 URLError。"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        ctype = resp.headers.get_content_charset() or "utf-8"
        # 站群中文页多用 utf-8，少数 gbk；按 ctype 解码，失败回退 utf-8 strict 替换
        try:
            return raw.decode(ctype), ctype
        except (UnicodeDecodeError, LookupError):
            return raw.decode("utf-8", errors="replace"), ctype


def build_paginated_urls(base: str, max_pages: int) -> Iterable[str]:
    """猜测站群分页格式：list.htm → list_2.htm / list2.htm / list_psp_2.htm / list-2.htm。

    多数站群都支持其中至少一种，但本爬虫只尝试几种；找不到的栏目只抓首页。
    """
    yield base
    if max_pages <= 1:
        return
    for n in range(2, max_pages + 1):
        candidates = [
            base.replace("list.htm", f"list_{n}.htm"),
            base.replace("list.htm", f"list{n}.htm"),
            base.replace("list.htm", f"list_psp_{n}.htm"),
        ]
        # 这里不去 HEAD 试探；下一轮 fetch 时 404 自然跳过
        for url in candidates:
            yield url


def crawl_listing(url: str, max_pages: int, delay: float) -> list[dict]:
    """抓取列表页（含分页），合并所有文章链接。"""
    items = []
    seen_urls: set[str] = set()
    for page_url in build_paginated_urls(url, max_pages):
        try:
            html, _ = http_get(page_url)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # 没有更多分页
                break
            print(f"  [WARN] GET {page_url} failed: {e}", file=sys.stderr)
            continue
        except Exception as e:
            print(f"  [WARN] GET {page_url} error: {e}", file=sys.stderr)
            continue

        parser = ListPageParser(page_url)
        parser.feed(html)
        new = 0
        for it in parser.items:
            if it["url"] not in seen_urls:
                seen_urls.add(it["url"])
                items.append(it)
                new += 1
        print(f"  [list] {page_url}  -> {new} new")
        if new == 0 and page_url != url:
            break
        time.sleep(delay)
    return items


def crawl_detail(url: str, delay: float) -> dict:
    """抓取详情页正文。失败时返回空 content，由调用方决定是否丢弃。"""
    html, _ = http_get(url)
    p = DetailPageParser()
    p.feed(html)
    time.sleep(delay)
    return {"title": p.title, "content": p.content}


# ---------------------------------------------------------------- 编排
def derive_id(site: str, cat: str, idx: int) -> str:
    return f"{site}_{cat}_{idx:03d}"


def crawl_one(list_url: str, category: str, source: str,
              max_pages: int, delay: float) -> list[dict]:
    """抓一个栏目：列表 → 详情。"""
    print(f"\n[栏目] {source} / {category}  → {list_url}")
    items = crawl_listing(list_url, max_pages, delay)
    print(f"  → 共 {len(items)} 篇文章")
    out_records: list[dict] = []
    site_key = list_url.split("//", 1)[1].split(".", 1)[0]
    for idx, it in enumerate(items, start=1):
        try:
            d = crawl_detail(it["url"], delay)
        except Exception as e:
            print(f"  [SKIP] {it['url']}  {e}")
            continue
        if not d["content"]:
            print(f"  [SKIP-empty] {it['url']}  ({it['title']})")
            continue
        rec = {
            "id": derive_id(site_key, category, idx),
            "source": source,
            "category": category,
            "url": it["url"],
            "title": d["title"] or it["title"],
            "date": it["date"],
            "content": d["content"],
        }
        out_records.append(rec)
        print(f"  [+] {rec['title'][:40]}... ({len(d['content'])} 字)")
    return out_records


def main() -> None:
    p = argparse.ArgumentParser(description="爬取南工业职四部门通知")
    p.add_argument("--site", choices=["jwc", "xsc", "xxh", "hqglc", "all"],
                   default="all")
    p.add_argument("--max-pages", type=int, default=2,
                   help="每个列表最多翻几页（默认 2）")
    p.add_argument("--delay", type=float, default=1.5,
                   help="请求间隔秒数（默认 1.5，避免压垮学校服务器）")
    args = p.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    targets = LIST_PAGES
    if args.site != "all":
        site_map = {"jwc": "jwc", "xsc": "xsc", "xxh": "xxh", "hqglc": "hqglc"}
        targets = [t for t in LIST_PAGES if site_map[args.site] in t[0]]

    all_records: list[dict] = []
    for url, cat, src in targets:
        recs = crawl_one(url, cat, src, args.max_pages, args.delay)
        # 每栏目单独存一份 + 全部合并
        site_key = url.split("//", 1)[1].split(".", 1)[0]
        out_path = OUT_DIR / f"{site_key}_{cat}.json"
        out_path.write_text(
            json.dumps({"source": src, "category": cat, "records": recs},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  → 写入 {out_path}  ({len(recs)} 条)")
        all_records.extend(recs)

    all_path = OUT_DIR / "all.json"
    all_path.write_text(
        json.dumps({"records": all_records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n总计 {len(all_records)} 条 → {all_path}")


if __name__ == "__main__":
    main()