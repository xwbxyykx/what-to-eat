"""resolve_location：确定性地理编码。坐标只来自高德，LLM 不参与空间计算。"""
from __future__ import annotations

import structlog

from ..state import ReqState

log = structlog.get_logger(__name__)


def locate_node(registry, config):
    def _node(state: ReqState) -> dict:
        req = state.get("requirement") or {}
        desc = req.get("location_desc") or state.get("location_desc")
        radius = int(state.get("radius") or config.default_radius)

        if desc:
            res = registry.call("amap_geocode", address=desc)
            if res and getattr(res, "location", ""):
                return {
                    "location": res.location,
                    "city": res.city or config.default_city,
                    "location_desc": desc,
                    "radius": radius,
                    "location_source": "user",
                }

        # 无位置/解析失败：默认城市兜底
        res = registry.call("amap_geocode", address=config.default_city)
        if res and getattr(res, "location", ""):
            log.info("location_use_default", city=config.default_city)
            return {
                "location": res.location,
                "city": config.default_city,
                "location_desc": desc or config.default_city,
                "radius": radius,
                "location_source": "default",
            }
        return {"location_source": "error"}

    return _node
