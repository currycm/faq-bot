"""
将 data/raw_notices/ 下的原始通知 JSON 转成 qa_corpus.json 格式。

设计要点：
- 每条通知 → 1 个 intent（粒度与"语义独立的话题"一致）
- questions 至少 5 条同义改写（含标题 + 自然口语化问法）
- answer 用通知正文，截断到合适长度（≤ 350 字）

用法：
    python scripts/raw_to_corpus.py
        [--input data/raw_notices/notices_seed.json]
        [--output data/qa_corpus.json]
        [--merge]   # 与已有 corpus 合并
        [--max-answer-len 350]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# 每个通知的同义问法：手写为主，覆盖高频自然问法
QUESTION_TEMPLATES: dict[str, list[str]] = {
    "jwc_001": [
        "体育俱乐部怎么选课",
        "体育课怎么选",
        "什么时候选体育课",
        "选体育课要注意什么",
        "2025级体育选课什么时候开始",
        "体育课能选几个",
        "体育课多选了怎么办",
        "体育课与实训课冲突怎么办",
    ],
    "jwc_002": [
        "专业选修课怎么选",
        "专业选修课什么时候选",
        "选课网址是什么",
        "选课系统登录密码是什么",
        "选错课能退吗",
        "少选课影响毕业吗",
        "多选课要交钱吗",
        "选课截止后还能换吗",
    ],
    "jwc_003": [
        "退役士兵专转本怎么报名",
        "退役大学生士兵专转本什么时候报名",
        "专转本报名网址",
        "退役士兵专转本免试吗",
        "专转本考查什么时候考",
        "退役士兵专转本能填几个志愿",
        "三等功退役士兵专转本加分吗",
    ],
    "jwc_004": [
        "学士学位怎么申请",
        "学士学位授予条件是什么",
        "学士学位公示在哪里查",
        "对学士学位有异议怎么反映",
        "学位办电话多少",
        "本科毕业怎么拿学位证",
    ],
    "xsc_001": [
        "走读怎么申请",
        "走读手续怎么办",
        "申请走读需要什么材料",
        "走读能免住宿费吗",
        "什么时候办走读",
        "南京籍学生可以走读吗",
        "父母不在南京能走读吗",
        "走读申请表在哪",
    ],
    "xsc_002": [
        "宿舍6S是什么",
        "宿舍6S认证怎么申请",
        "宿舍6S认证有什么用",
        "宿舍6S不达标会怎样",
        "6S认证成绩影响奖学金吗",
        "宿舍6S检查标准",
        "宿舍能用大功率电器吗",
    ],
    "xsc_003": [
        "国家奖学金怎么申请",
        "国家奖学金多少钱",
        "国家奖学金评选条件",
        "国家奖学金什么时候评",
        "国家奖学金学习成绩要求",
        "国家奖学金证书有用吗",
        "国家奖学金审批流程",
    ],
    "xsc_004": [
        "优秀毕业生怎么评选",
        "优秀毕业生有什么用",
        "优秀毕业生评选条件",
        "优秀毕业生比例多少",
        "怎么申请优秀毕业生",
        "优秀毕业生公示多久",
    ],
    "xxh_001": [
        "校园WiFi频繁掉线怎么办",
        "NIIT-WIFI连上就掉",
        "校园网老是断",
        "怎么关闭随机MAC",
        "苹果手机校园网掉线",
        "安卓手机校园网掉线",
        "锁屏就断网怎么解决",
        "校园网不让锁屏怎么设",
    ],
    "xxh_002": [
        "校园邮箱怎么申请",
        "学生邮箱怎么开",
        "教育邮箱申请流程",
        "校园邮箱初始密码",
        "校园邮箱登录网址",
        "校园邮箱毕业会注销吗",
        "邮箱密码忘了怎么办",
    ],
    "xxh_003": [
        "智能机器人怎么用",
        "AI辅导员怎么进",
        "教务喵在哪",
        "南工智答是什么",
        "校园智能机器人入口",
        "AI辅导员能问什么",
        "智能机器人转人工",
    ],
    "xxh_004": [
        "校园云盘怎么用",
        "够快云盘怎么登录",
        "校园云盘容量多大",
        "校园云盘怎么扩容",
        "云盘客户端在哪下",
        "校园云盘学生能用吗",
        "云盘联系谁",
    ],
    "xxh_005": [
        "校园网认证网址变了",
        "新版校园网认证怎么登录",
        "校园网认证登录不上",
        "办公区有线网怎么认证",
        "机房上网认证网址",
        "校园网报修电话",
        "校园网掉线报修在哪",
    ],
    "jwc_005": [
        "教材在哪里领",
        "教材怎么领",
        "教材费怎么交",
        "教材什么时候发",
        "新学期教材领",
        "教材领错了怎么办",
        "教材有异议怎么反映",
    ],
    "jwc_006": [
        "素质拓展选修课怎么选",
        "素质拓展是什么",
        "素质拓展选课网址",
        "素质拓展选课时间",
        "素质拓展选课学分要求",
        "素质拓展选课能选几门",
        "少选素质拓展影响毕业吗",
    ],
    "jwc_007": [
        "乐群楼为什么封楼",
        "教学楼封闭通知",
        "考场封闭什么时候解封",
        "仙林校区教学楼什么时候封",
        "天堂校区教学楼封闭",
        "英语考试考场在哪",
        "考场封闭期间能进吗",
    ],
    "xxh_006": [
        "OpenClaw是什么",
        "数字龙虾是什么软件",
        "校园网禁止用什么软件",
        "OpenClaw为什么禁用",
        "数字龙虾可以装吗",
        "AI智能体风险",
        "校园禁用软件有哪些",
        "已装OpenClaw怎么处理",
    ],
    "jwc_008": [
        "公共选修课怎么选",
        "公选课和素质拓展区别",
        "公选课选课网址",
        "公选课选课时间",
        "思政选择性必修怎么修",
        "黄炎培职业教育思想怎么选",
        "改革开放史选修怎么选",
        "公选课忘了密码怎么办",
    ],
    "jwc_009": [
        "重修怎么报名",
        "重修在哪报",
        "重修缴费多少",
        "重修缴费方式",
        "重修考试什么时候考",
        "重修报名网址",
        "往届生怎么重修",
        "结业学生怎么重修",
    ],
    "jwc_010": [
        "英语四级怎么报名",
        "CET4报名",
        "英语六级怎么报名",
        "CET6什么时候考",
        "四六级报名网址",
        "四六级报名费多少",
        "四六级缺考会怎样",
        "四级多少分能报六级",
    ],
    "jwc_011": [
        "英语AB级怎么报名",
        "英语应用能力考试报名",
        "A级B级怎么选",
        "AB级考试时间",
        "专科英语毕业要求",
        "英语AB级报名表",
        "AB级考试缴费方式",
        "艺术学院AB级考哪个",
    ],
    "jwc_012": [
        "体育俱乐部怎么选",
        "体育俱乐部有哪些",
        "2024级体育选课时间",
        "体育保健课怎么申请",
        "体育课自备用具",
        "体育课哪个好",
        "体育课能换吗",
        "哪些情况不能选体育俱乐部",
    ],
    "xsc_005": [
        "学业奖学金怎么评",
        "学业奖学金有几等",
        "学业奖学金多少钱",
        "学业奖学金要申请吗",
        "学业奖学金和国家奖学金区别",
        "特等奖学金怎么评",
        "学业奖学金异议电话",
    ],
    "xsc_006": [
        "家庭经济困难怎么认定",
        "贫困生认定流程",
        "贫困认定需要什么材料",
        "贫困认定时间",
        "贫困认定档次",
        "怎么申请助学金",
        "贫困认定在哪个办公室",
        "贫困认定异议找谁",
    ],
    "xsc_007": [
        "退役士兵助学金多少",
        "退役士兵国家助学金",
        "退役士兵怎么申请资助",
        "退役士兵学费补偿",
        "退役士兵能享受什么资助",
        "退役士兵助学金发几个月",
        "退役士兵助学金申请材料",
    ],
    "hqglc_001": [
        "宿舍能用吹风机吗",
        "宿舍能用卷发棒吗",
        "宿舍大功率电器有哪些",
        "什么电器不能带进宿舍",
        "宿舍私拉电线会怎样",
        "宿舍违规电器处理",
        "宿舍空调怎么申请",
        "冬季宿舍用电",
    ],
}

# 把每个通知映射到 intent tag 与原始语料合并
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="raw_notices → qa_corpus.json")
    p.add_argument("--input", type=Path, default=REPO_ROOT / "data/raw_notices/notices_seed.json")
    p.add_argument("--output", type=Path, default=REPO_ROOT / "data/qa_corpus.json")
    p.add_argument("--merge", action="store_true",
                   help="与现有 corpus 合并（按 tag 去重）")
    p.add_argument("--max-answer-len", type=int, default=350)
    return p.parse_args()


def derive_tag(source: str, idx: int, notice_id: str) -> str:
    """根据 source + notice_id 派生语义化 tag。"""
    sid = notice_id.split("_", 1)[0]
    mid = notice_id.split("_", 1)[1]
    tag_map = {
        "jwc_001": "jwc_pe_select",
        "jwc_002": "jwc_major_select",
        "jwc_003": "jwc_veteran_transfer",
        "jwc_004": "jwc_bachelor_degree",
        "xsc_001": "xsc_commute_apply",
        "xsc_002": "xsc_dorm_6s",
        "xsc_003": "xsc_national_scholarship",
        "xsc_004": "xsc_excellent_graduate",
        "xxh_001": "xxh_wifi_drop",
        "xxh_002": "xxh_student_email",
        "xxh_003": "xxh_smart_bot",
        "xxh_004": "xxh_cloud_disk",
        "xxh_005": "xxh_net_auth",
        "jwc_005": "jwc_textbook_pickup",
        "jwc_006": "jwc_quality_select",
        "jwc_007": "jwc_classroom_closed",
        "xxh_006": "xxh_openclaw_ban",
        "jwc_008": "jwc_public_select",
        "jwc_009": "jwc_retake_signup",
        "jwc_010": "jwc_cet_signup",
        "jwc_011": "jwc_english_ab",
        "jwc_012": "jwc_pe_club_select",
        "xsc_005": "xsc_academic_scholarship",
        "xsc_006": "xsc_impoverish_certify",
        "xsc_007": "xsc_veteran_aid",
        "hqglc_001": "hqglc_dorm_electric",
    }
    return tag_map.get(notice_id, f"{sid}_custom_{idx:03d}")


def truncate_answer(text: str, max_len: int) -> str:
    """截断正文到 max_len，优先在句号处截断。"""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    # 找到最后一个句号/分号
    for sep in ["。", "；", ";", ". ", "!?", "？"]:
        last = cut.rfind(sep)
        if last > max_len * 0.6:
            return cut[:last + 1] + "（详见原文）"
    return cut + "…（详见原文）"


def build_intent(notice: dict, max_answer_len: int) -> dict:
    tag = derive_tag(notice["source"], 0, notice["id"])
    questions = QUESTION_TEMPLATES.get(notice["id"], [notice["title"]])
    answer = truncate_answer(notice["content"], max_answer_len)
    return {
        "tag": tag,
        "questions": questions,
        "answer": answer,
        "_meta": {
            "source": notice["source"],
            "category": notice.get("category"),
            "url": notice["url"],
            "title": notice["title"],
            "date": notice.get("date"),
            "type": "real_notice_v3",
        },
    }


def main() -> None:
    args = parse_args()
    raw = json.loads(args.input.read_text(encoding="utf-8"))
    new_intents = [build_intent(n, args.max_answer_len) for n in raw["notices"]]
    print(f"[gen] 新增 {len(new_intents)} 个真实通知意图")

    if args.merge and args.output.exists():
        existing = json.loads(args.output.read_text(encoding="utf-8"))
        existing_tags = {i["tag"] for i in existing.get("intents", [])}
        added = [i for i in new_intents if i["tag"] not in existing_tags]
        existing.setdefault("intents", []).extend(added)
        out = existing
        print(f"[merge] 已存在 {len(existing_tags)} 个，新增 {len(added)} 个")
    else:
        out = {
            "school": raw.get("school", ""),
            "version": "v3-real-corpus",
            "intents": new_intents,
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[write] {args.output} -> {len(out['intents'])} 个意图")


if __name__ == "__main__":
    main()