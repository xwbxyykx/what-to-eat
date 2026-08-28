"""search_restaurants：周边搜索为主，文本搜索/扩大半径做降级，无结果时给出兜底。"""
from __future__ import annotations

import structlog

from ..state import ReqState

log = structlog.get_logger(__name__)


def search_node(registry, config):
    def _node(state: ReqState) -> dict:
        location = state.get("location")
        req = state.get("requirement") or {}
        keywords = " ".join((req.get("dish") or []) + (req.get("cuisine") or []))
        city = state.get("city") or config.default_city
        pois = []

        # 1) 周边搜索（默认路径）
        if location:
            pois = registry.call(
                "amap_place_around",
                location=location,
                radius=int(state.get("radius") or config.default_radius),
                keywords=keywords or None,
            )
            log.info("search_around", count=len(pois), radius=state.get("radius"))

        # 2) 降级：文本搜索（有菜品关键词时）
        if not pois and keywords:
            pois = registry.call("amap_place_text", keywords=keywords, city=city)

        # 3) 降级：扩大半径再试一次
        if not pois and location:
            pois = registry.call(
                "amap_place_around",
                location=location,
                radius=int(state.get("radius") or config.default_radius) * 2,
                keywords=keywords or None,
            )

        if not pois:
            return {
                "candidates": [],
                "no_result": True,
                "search_hint": "该条件下没有找到合适的餐厅。换个位置、放宽预算或去掉关键词再试试？",
            }

        return {"candidates": [p.to_dict() for p in pois]}

    return _node
