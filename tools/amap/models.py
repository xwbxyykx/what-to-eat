"""高德返回数据的规范化模型。"""
from __future__ import annotations

from dataclasses import dataclass, field


def _to_float(v) -> float | None:
    """高德 biz_ext 的 rating/cost 常是数字字符串或缺失，统一防御式解析。"""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s in ("[]", "null", "None"):
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


@dataclass
class POI:
    name: str
    address: str = ""
    location: str = ""                 # "lng,lat"（GCJ-02，经度在前）
    distance: int = 0                  # 米
    tel: str = ""
    business_area: str = ""
    category: str = ""                 # 高德 type 字符串
    rating: float | None = None
    cost: float | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "address": self.address,
            "location": self.location,
            "distance": self.distance,
            "tel": self.tel,
            "business_area": self.business_area,
            "category": self.category,
            "rating": self.rating,
            "cost": self.cost,
        }

    @classmethod
    def from_amap_v3(cls, poi: dict) -> "POI":
        biz = poi.get("biz_ext") or {}
        dist_raw = poi.get("distance")
        return cls(
            name=poi.get("name", ""),
            address=poi.get("address", ""),
            location=poi.get("location", ""),
            distance=int(float(dist_raw)) if dist_raw not in (None, "") else 0,
            tel=poi.get("tel", ""),
            business_area=poi.get("business_area", ""),
            category=poi.get("type", ""),
            rating=_to_float(biz.get("rating")),
            cost=_to_float(biz.get("cost")),
        )


@dataclass
class GeocodeResult:
    location: str                      # "lng,lat"
    city: str = ""
    district: str = ""
    formatted_address: str = ""
    level: str = field(default="")

    def to_dict(self) -> dict:
        return {
            "location": self.location,
            "city": self.city,
            "district": self.district,
            "formatted_address": self.formatted_address,
            "level": self.level,
        }
