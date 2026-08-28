"""内置 mock 数据：无高德 Key 时保证最小闭环可跑。

⚠️ 以下餐厅名称/地址均为**虚构占位**，仅用于演示流程，不指向真实商户。
"""
from __future__ import annotations

from .models import POI, GeocodeResult

GUANGZHOU_CENTER = "113.2644,23.1291"
TIANHE = "113.3220,23.1350"
ZHUJIANG_NEW = "113.3228,23.1200"

_PLACES = {
    "珠江新城": ZHUJIANG_NEW,
    "天河": TIANHE,
    "广州": GUANGZHOU_CENTER,
    "广州市": GUANGZHOU_CENTER,
    "公司": ZHUJIANG_NEW,
    "家": TIANHE,
    "北京": "116.4074,39.9042",
    "上海": "121.4737,31.2304",
    "深圳": "114.0579,22.5431",
}


def mock_geocode(address: str, default_city: str = "广州") -> GeocodeResult | None:
    """mock 地理编码：命中已知地名返回坐标，否则兜底默认城市中心。"""
    for key, loc in _PLACES.items():
        if key in address:
            return GeocodeResult(
                location=loc,
                city="广州" if key in ("广州", "广州市") else key,
                formatted_address=address,
                level="兴趣点",
            )
    center = _PLACES.get(default_city, GUANGZHOU_CENTER)
    return GeocodeResult(
        location=center,
        city=default_city,
        formatted_address=f"{default_city}（默认城市兜底）",
        level="默认",
    )


def _restaurants() -> list[POI]:
    rows = [
        # (name, location, distance, area, rating, cost, tags)
        ("川香居（川菜）", "113.3250,23.1310", 420, "体育西", 4.6, 68, "川菜 辣 水煮鱼"),
        ("辣味轩（重庆火锅）", "113.3280,23.1260", 860, "珠江新城", 4.5, 108, "火锅 辣 牛油"),
        ("粤味轩（粤菜）", "113.3180,23.1330", 300, "体育西", 4.2, 78, "粤菜 清淡 白切鸡"),
        ("港式茶餐厅", "113.3300,23.1210", 900, "珠江新城", 4.3, 55, "港式 茶餐厅 烧腊"),
        ("沸腾火锅（川味）", "113.3220,23.1280", 640, "天河", 4.1, 120, "火锅 麻辣"),
        ("粥面世家", "113.3150,23.1360", 520, "体育西", 4.0, 35, "粥 面 清淡"),
        ("广式早茶楼", "113.3200,23.1340", 380, "天河", 4.7, 88, "早茶 广式 点心"),
        ("日式拉面馆", "113.3270,23.1250", 720, "珠江新城", 4.4, 62, "日式 拉面"),
        ("轻食沙拉店", "113.3240,23.1230", 550, "天河", 4.0, 45, "轻食 沙拉 健康 清淡"),
        ("湘楚风味馆", "113.3310,23.1190", 1100, "珠江新城", 4.2, 80, "湘菜 辣 小炒"),
    ]
    pois = []
    for name, loc, dist, area, rating, cost, _tags in rows:
        pois.append(
            POI(
                name=name,
                location=loc,
                distance=dist,
                business_area=area,
                rating=rating,
                cost=cost,
                address=f"{area}·演示路{name[0]}号（Mock）",
                category="餐饮服务;中餐厅;特色/地方风味餐厅",
            )
        )
    return pois


def mock_around(location: str, radius: int = 5000, keywords: str | None = None) -> list[POI]:
    """mock 周边搜索：按距离排序 + 可选关键词过滤。"""
    pois = _restaurants()
    if radius < 5000:
        pois = [p for p in pois if p.distance <= radius]
    if keywords:
        kws = [k for k in keywords.replace("，", " ").split() if k]
        if kws:
            pois = [p for p in pois if any(k in p.name for k in kws)]
    return sorted(pois, key=lambda p: p.distance)


def mock_text(keywords: str, city: str | None = None) -> list[POI]:
    """mock 文本搜索：按关键词过滤（忽略城市）。"""
    pois = _restaurants()
    kws = [k for k in keywords.replace("，", " ").split() if k]
    if kws:
        pois = [p for p in pois if any(k in p.name for k in kws)]
    return sorted(pois, key=lambda p: p.distance)
