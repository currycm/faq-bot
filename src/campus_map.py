# -*- coding: utf-8 -*-
"""校园地图（纯前端，无需后端）— 自包含图片查看器（底图，无标记）

实现：
    - 两张手绘地图（天堂校区 / 仙林校区）以 base64 内嵌进 HTML，无需静态文件服务器。
    - 缩放 / 拖拽由原生 JS 实现，**零外部依赖**：不加载 Leaflet / jQuery / Bootstrap /
      OSM 瓦片，因此完全离线的环境里也能正常显示与交互。
    - 当前仅展示手绘底图；POI 数据仍保留在 CAMPUSES 中，可按需恢复标记渲染。

为什么不用 Folium / Leaflet（2026-09 修复）：
    Folium 生成的 HTML 要向 cdn.jsdelivr.net、code.jquery.com 拉 Leaflet 等 12 个外部
    资源，并向 tile.openstreetmap.org 请求瓦片。离线或受限网络下这些请求全部失败，
    地图整块空白；而 iframe 内部脚本加载失败不会抛 Python 异常，旧代码的 try/except
    兜底因此永远不触发。改为自包含实现后，离线 / Docker / HF Spaces 表现一致。

首次切换不显示的坑（2026-09 修复）：
    地图位于 st.tabs 的第二个 tab，未激活时面板是隐藏的。iframe 里的脚本此时执行，
    wrap 的 clientWidth/Height 为 0；旧代码用 `||1` 兜底成 1x1，比例算成 1/图片宽，
    图片被缩到 1 像素 —— 用户看到的就是"切到地图 tab 第一次加载不出来"。
    现在改为：拿不到真实尺寸就不 fit，靠 requestAnimationFrame 重试 +
    ResizeObserver 监听，等面板可见后再自适应。

⚠️ 数据来源说明：
    - campus["center"] 为校区地理中心（估算值，请按需校准，仅用于让地图默认落在正确城市区域）。
    - pois 的 (x, y) 是「相对图片」的百分比：x:0=左 100=右；y:0=上 100=下。
      请按手绘图上的位置填写，不需要任何真实经纬度。
"""

from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

# 显式 import 模块再调用，而非 `st.components.v1.html(...)` 穿透式取属性——
# 后者是官方文档标注的 deprecated 写法（1.51.0 尚不告警，但注明后续会禁用）。
import streamlit.components.v1 as components

_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "campus_maps"

# 每个校区：图片文件名、地理中心(估算)、图片地理半跨度、POI 列表。
# POI 的 (x, y) 为图片内百分比：x 0→左 100→右，y 0→上 100→下。
CAMPUSES: dict[str, dict] = {
    "天堂校区": {
        "image": "campus_tiantang.jpg",
        "center": (32.072, 118.764),  # ⚠️ 估算：南京工业职业技术大学天堂校区附近，请校准
        "span_lat": 0.006,  # 图片覆盖约 ±0.006° 纬度 ≈ 1.3km
        "pois": [
            # 数据来源：天堂校区 手绘图坐标（原点=图片左上角，坐标=标签文字中心像素点，按 1468x960 换算百分比；x:0=左100=右, y:0=上100=下）
            {"name": "东门", "x": 13.6, "y": 22.9, "desc": "校门"},
            {"name": "西门", "x": 39.5, "y": 93.8, "desc": "校门"},
            {"name": "北苑一栋", "x": 11.6, "y": 33.3, "desc": "学生宿舍"},
            {"name": "北苑二栋", "x": 16.3, "y": 27.1, "desc": "学生宿舍"},
            {"name": "南苑一栋", "x": 52.8, "y": 15.6, "desc": "学生宿舍"},
            {"name": "南苑二栋", "x": 55.2, "y": 6.2, "desc": "学生宿舍"},
            {"name": "综合楼", "x": 33.4, "y": 21.9, "desc": "教学综合楼"},
            {"name": "艺术工坊", "x": 9.5, "y": 42.7, "desc": "艺术实训"},
            {"name": "艺术茶吧", "x": 26.2, "y": 30.2, "desc": "休闲配套"},
            {"name": "北苑餐厅", "x": 19.1, "y": 37.5, "desc": "食堂"},
            {"name": "南苑餐厅", "x": 52.8, "y": 18.8, "desc": "食堂"},
            {"name": "运动场", "x": 45.6, "y": 27.1, "desc": "田径场"},
            {"name": "风雨球场", "x": 49.0, "y": 41.7, "desc": "球类场地"},
            {"name": "篮球场", "x": 40.9, "y": 55.2, "desc": "篮球场地"},
            {"name": "停车场", "x": 49.0, "y": 77.1, "desc": "停车区域"},
            {"name": "校训石", "x": 30.0, "y": 39.6, "desc": "景观石刻"},
            {"name": "炎培园", "x": 35.4, "y": 68.8, "desc": "园林景观"},
            {"name": "颐礼台", "x": 45.6, "y": 13.5, "desc": "广场平台"},
        ],
    },
    "仙林校区": {
        "image": "campus_xianlin.jpg",
        "center": (32.115, 118.918),  # ⚠️ 估算：南京工业职业技术大学仙林校区附近，请校准
        "span_lat": 0.006,
        "pois": [
            # 数据来源：仙林校区 手绘图坐标（原点=图片左上角，坐标=标签文字中心像素点，按 1358x960 换算百分比；x:0=左100=右, y:0=上100=下）
            {"name": "北大门", "x": 50.8, "y": 8.3, "desc": "校门"},
            {"name": "西大门", "x": 3.7, "y": 47.9, "desc": "校门"},
            {"name": "南大门", "x": 38.3, "y": 96.9, "desc": "校门"},
            {"name": "海棠苑1栋", "x": 10.7, "y": 27.6, "desc": "学生宿舍"},
            {"name": "海棠苑2栋", "x": 10.7, "y": 21.9, "desc": "学生宿舍"},
            {"name": "筠竹苑1栋", "x": 16.9, "y": 28.1, "desc": "学生宿舍"},
            {"name": "筠竹苑2栋", "x": 16.9, "y": 18.8, "desc": "学生宿舍"},
            {"name": "梧桐苑1-2栋", "x": 10.9, "y": 45.8, "desc": "学生宿舍"},
            {"name": "梧桐苑3栋", "x": 10.2, "y": 39.6, "desc": "学生宿舍"},
            {"name": "梧桐苑4-5栋", "x": 10.2, "y": 34.4, "desc": "学生宿舍"},
            {"name": "香樟苑1栋", "x": 17.7, "y": 41.7, "desc": "学生宿舍"},
            {"name": "香樟苑2栋", "x": 17.7, "y": 35.4, "desc": "学生宿舍"},
            {"name": "雪松苑1-2栋", "x": 10.7, "y": 65.6, "desc": "学生宿舍"},
            {"name": "雪松苑3栋", "x": 10.7, "y": 60.4, "desc": "学生宿舍"},
            {"name": "雪松苑4-5栋", "x": 10.7, "y": 55.2, "desc": "学生宿舍"},
            {"name": "青教公寓B1", "x": 18.3, "y": 66.1, "desc": "公寓"},
            {"name": "青教公寓B2", "x": 11.8, "y": 72.4, "desc": "公寓"},
            {"name": "筠竹苑G1", "x": 57.1, "y": 15.6, "desc": "学生宿舍"},
            {"name": "筠竹苑G2", "x": 57.1, "y": 18.8, "desc": "学生宿舍"},
            {"name": "筠竹苑G3", "x": 58.5, "y": 21.9, "desc": "学生宿舍"},
            {"name": "筠竹苑G4", "x": 57.1, "y": 25.0, "desc": "学生宿舍"},
            {"name": "双创大楼", "x": 64.1, "y": 17.7, "desc": "宿舍/实训楼"},
            {"name": "乐业楼", "x": 53.0, "y": 43.8, "desc": "教学楼"},
            {"name": "敬业楼", "x": 53.0, "y": 55.2, "desc": "教学楼"},
            {"name": "求真楼", "x": 60.8, "y": 55.2, "desc": "教学楼"},
            {"name": "乐群楼", "x": 52.3, "y": 70.8, "desc": "教学楼"},
            {"name": "行政楼", "x": 50.4, "y": 85.4, "desc": "行政办公"},
            {"name": "图书馆（求是楼）", "x": 60.8, "y": 43.8, "desc": "图书馆"},
            {"name": "学术交流中心", "x": 31.7, "y": 80.2, "desc": "会议接待"},
            {"name": "大学生创新发展中心", "x": 24.7, "y": 76.0, "desc": "创新创业"},
            {"name": "人工智能及工业互联网产教融合大楼（施工中）", "x": 61.1, "y": 71.9, "desc": "在建实训楼"},
            {"name": "第一食堂", "x": 23.6, "y": 26.0, "desc": "食堂"},
            {"name": "快递服务中心", "x": 23.6, "y": 17.7, "desc": "后勤服务"},
            {"name": "新体育场", "x": 36.5, "y": 34.4, "desc": "运动场"},
            {"name": "老体育场", "x": 40.9, "y": 34.4, "desc": "运动场"},
            {"name": "体育馆", "x": 44.6, "y": 27.1, "desc": "室内体育馆"},
            {"name": "运动场（篮球场）", "x": 30.2, "y": 22.9, "desc": "球类场地"},
            {"name": "拓展场地", "x": 39.8, "y": 18.8, "desc": "拓展实训场地"},
            {"name": "松山湖", "x": 36.8, "y": 54.2, "desc": "湖泊"},
            {"name": "文化广场", "x": 24.3, "y": 33.3, "desc": "广场"},
            {"name": "百工桥", "x": 24.3, "y": 56.2, "desc": "景观桥"},
            {"name": "匠心亭", "x": 27.2, "y": 66.7, "desc": "亭子景观"},
            {"name": "校训石刻", "x": 37.6, "y": 78.1, "desc": "景观石刻"},
            {"name": "黄炎培广场", "x": 37.6, "y": 85.4, "desc": "纪念广场"},
            {"name": "松山湖学生公寓", "x": 35.3, "y": 82.3, "desc": "临湖公寓"},
            {"name": "航空实训基地", "x": 50.1, "y": 27.1, "desc": "航空实训场地"},
            {"name": "城市轨道室外综合实训基地", "x": 50.1, "y": 16.7, "desc": "轨道实训场地"},
            {"name": "青春舞台", "x": 30.2, "y": 43.8, "desc": "户外舞台"},
        ],
    },
}


def _img_data_uri(path: Path) -> str:
    """把图片读成 data URI，内嵌进 Folium HTML，免去静态文件服务。"""
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


# 自包含查看器模板：HTML + 原生 JS，**不引用任何外部资源**。
# 图片以 base64 内嵌（__SRC__ 占位符），因此离线 / 无静态服务器也能显示与交互。
_VIEWER_TEMPLATE = """
<style>
  .cm-wrap{position:relative;width:100%;height:500px;overflow:hidden;
           background:#ececec;border:1px solid #d8d8d8;border-radius:10px;
           cursor:grab;touch-action:none}
  .cm-wrap.grabbing{cursor:grabbing}
  .cm-img{position:absolute;left:0;top:0;transform-origin:0 0;
          user-select:none;-webkit-user-drag:none;pointer-events:none}
  .cm-bar{margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  .cm-btn{border:1px solid #c9c9c9;background:#fff;border-radius:6px;
          padding:4px 12px;font-size:13px;cursor:pointer;color:#333}
  .cm-btn:hover{background:#f2f6ff}
  .cm-tip{font-size:12px;color:#888}
</style>
<div class="cm-wrap" id="cm-wrap">
  <img class="cm-img" id="cm-img" src="__SRC__" alt="校园地图">
</div>
<div class="cm-bar">
  <button class="cm-btn" id="cm-zin">放大 ＋</button>
  <button class="cm-btn" id="cm-zout">缩小 －</button>
  <button class="cm-btn" id="cm-reset">重置</button>
  <span class="cm-tip">滚轮缩放 · 按住拖动移动</span>
</div>
<script>
(function(){
  var wrap=document.getElementById('cm-wrap');
  var img=document.getElementById('cm-img');
  var scale=1,tx=0,ty=0;
  var MIN=0.2,MAX=8;
  var userMoved=false;   // 用户手动缩放/拖动后不再自动 fit，避免重置他的视角
  function apply(){
    img.style.transform='translate('+tx+'px,'+ty+'px) scale('+scale+')';
  }
  function fit(){
    var cw=wrap.clientWidth, ch=wrap.clientHeight;
    var iw=img.naturalWidth, ih=img.naturalHeight;
    if(!cw||!ch||!iw||!ih) return false;   // 尺寸/图片还没就绪
    scale=Math.min(cw/iw, ch/ih);
    tx=(cw-iw*scale)/2; ty=(ch-ih*scale)/2;
    apply();
    return true;
  }
  // 首次加载的坑（2026-09 修复）：地图在 Streamlit 的 tab 里，未激活的
  // 面板是隐藏的，此时 wrap 的 clientWidth/Height 为 0，图片也还没解码完。
  // 旧代码写的是 `wrap.clientWidth||1`，于是按 1x1 的容器算比例，得到
  // scale≈1/图片宽，图被缩成 1 像素——表现就是"切到地图 tab 第一次打不开"。
  // 现在拿不到真实尺寸就**不 fit**，用 rAF + ResizeObserver 等到面板可见
  // （或图片解码完）再 fit，因此首次切换、窗口缩放都能正确自适应。
  var tries=0;
  function fitWhenReady(){
    if(userMoved) return;
    if(fit()) return;
    if(++tries>600) return;          // 约 10s 后放弃，后续交给 ResizeObserver
    requestAnimationFrame(fitWhenReady);
  }
  if(img.complete){fitWhenReady();} else {img.onload=fitWhenReady;}
  if(window.ResizeObserver){
    new ResizeObserver(function(){ if(!userMoved) fit(); }).observe(wrap);
  }
  wrap.addEventListener('wheel',function(e){
    e.preventDefault();
    var r=wrap.getBoundingClientRect();
    zoomAt(e.clientX-r.left, e.clientY-r.top, e.deltaY<0?1.15:1/1.15);
  },{passive:false});
  function zoomAt(cx,cy,f){
    var ns=Math.min(MAX,Math.max(MIN,scale*f));
    if(ns===scale) return;
    userMoved=true;
    var ix=(cx-tx)/scale, iy=(cy-ty)/scale;
    scale=ns; tx=cx-ix*scale; ty=cy-iy*scale;
    apply();
  }
  var drag=false,sx=0,sy=0;
  wrap.addEventListener('mousedown',function(e){
    drag=true; userMoved=true; sx=e.clientX-tx; sy=e.clientY-ty;
    wrap.classList.add('grabbing');
  });
  window.addEventListener('mousemove',function(e){
    if(!drag) return;
    tx=e.clientX-sx; ty=e.clientY-sy; apply();
  });
  window.addEventListener('mouseup',function(){
    drag=false; wrap.classList.remove('grabbing');
  });
  wrap.addEventListener('touchstart',function(e){
    if(e.touches.length===1){
      drag=true; userMoved=true; sx=e.touches[0].clientX-tx; sy=e.touches[0].clientY-ty;
    }
  },{passive:true});
  wrap.addEventListener('touchmove',function(e){
    if(!drag||e.touches.length!==1) return;
    e.preventDefault();
    tx=e.touches[0].clientX-sx; ty=e.touches[0].clientY-sy; apply();
  },{passive:false});
  wrap.addEventListener('touchend',function(){drag=false;});
  document.getElementById('cm-zin').onclick=function(){
    zoomAt(wrap.clientWidth/2, wrap.clientHeight/2, 1.3);
  };
  document.getElementById('cm-zout').onclick=function(){
    zoomAt(wrap.clientWidth/2, wrap.clientHeight/2, 1/1.3);
  };
  // 重置 = 回到自动适配，并解除"用户已操作"锁定
  document.getElementById('cm-reset').onclick=function(){userMoved=false; fit();};
})();
</script>
"""


@st.cache_resource(show_spinner="正在加载校园地图…")
def _build_viewer_html(campus_key: str) -> str:
    """生成自包含查看器 HTML（按校区缓存，避免重复做 base64 编码）。"""
    campus = CAMPUSES[campus_key]
    img_path = _ASSET_DIR / campus["image"]
    return _VIEWER_TEMPLATE.replace("__SRC__", _img_data_uri(img_path))


def render_campus_map() -> None:
    """在校园地图 tab 中渲染：校区切换 + 手绘地图底图（无标记）。"""
    st.caption("手绘地图支持滚轮缩放与拖动；可在下方切换校区。")

    campus_key = st.selectbox("选择校区", list(CAMPUSES.keys()), index=0, key="campus_select")

    try:
        # 自包含 HTML（图片 base64 内嵌、零外部请求），离线也能显示。
        components.html(_build_viewer_html(campus_key), height=560, scrolling=False)
    except Exception:
        # 兜底：iframe 渲染失败时显示手绘原图，保证地图始终可见。
        img_path = _ASSET_DIR / CAMPUSES[campus_key]["image"]
        if img_path.exists():
            st.image(str(img_path), caption=campus_key, use_container_width=True)
        else:
            st.warning(f"地图图片缺失：{img_path.name}")
