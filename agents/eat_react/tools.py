"""eat_react 工具层：把 harness 已注册的 AMAP 工具包装成 langchain @tool 供 LLM 调用。

复用已注册工具（单一数据源，自动带 mock/real）。AMAP 返回 dataclass（GeocodeResult/POI），
不能直接进 ToolMessage.content，故每个 wrapper 转 to_dict()/JSON 字符串。
"""
from __future__ import annotations

import json
from typing import Optional

from langchain_core.tools import BaseTool, tool
from langgraph.types import interrupt

from agents.eat_agent.nodes.score import score_node
from harness.core import Harness


def build_tools(harness: Harness) -> list[BaseTool]:
    registry = harness.tools
    config = harness.config

    @tool
    def amap_geocode(address: str, city: Optional[str] = None) -> dict:
        """地理编码：把自然语言地址/地标/商圈解析为 GCJ-02 坐标。返回单个 dict，必有 'location'（'lng,lat'）。"""
        res = registry.call("amap_geocode", address=address, city=city)
        return res.to_dict() if res is not None else {"error": "no result", "location": ""}

    @tool
    def amap_search_around(
        location: str,
        radius: int = config.default_radius,
        keywords: Optional[str] = None,
        page: int = 1,
        offset: int = config.search_page_size,
    ) -> str:
        """周边搜索：以 'lng,lat' 坐标 + 半径召回附近餐饮 POI（types=050000）。返回 JSON 数组字符串。"""
        pois = registry.call(
            "amap_place_around",
            location=location,
            radius=radius,
            keywords=keywords,
            page=page,
            offset=offset,
        )
        return json.dumps([p.to_dict() for p in pois], ensure_ascii=False)

    @tool
    def amap_search_text(
        keywords: str,
        city: Optional[str] = None,
        page: int = 1,
        offset: int = config.search_page_size,
    ) -> str:
        """文本搜索：按关键词+城市召回餐饮 POI（citylimit 严格限定城市）。返回 JSON 数组字符串。"""
        pois = registry.call(
            "amap_place_text",
            keywords=keywords,
            city=city,
            page=page,
            offset=offset,
        )
        return json.dumps([p.to_dict() for p in pois], ensure_ascii=False)

    @tool
    def score_candidates(
        candidates: list[dict],
        budget_preference: Optional[str] = None,
        cuisines: Optional[list[str]] = None,
        dishes: Optional[list[str]] = None,
    ) -> str:
        """可选：确定性规则打分（贝叶斯评分 + 预算/距离惩罚 + 菜系/菜品匹配），复用 eat_agent 的评分公式。
        返回 JSON：{"scored": [...], "top_k": [...]}，score 降序，每项带 breakdown。LLM 可选用它来排序，也可自行排序。"""
        requirement = {
            "budget_preference": budget_preference,
            "cuisine": cuisines or [],
            "dish": dishes or [],
        }
        # memory=None + 无 continuation_intent → _apply_dedupe 短路为 scored[:TOP_K]，绕过去重逻辑
        node = score_node(config, None)
        out = node({"candidates": candidates, "requirement": requirement})
        return json.dumps(out, ensure_ascii=False)

    @tool
    def ask_user(question: str) -> str:
        """向用户提问以澄清/补充需求。调用后图会暂停等待用户输入；用户的回答就是本工具的返回值。
        一次只问一个问题，并且必须单独调用。"""
        answer = interrupt({"type": "ask_user", "question": question})
        return str(answer)

    return [amap_geocode, amap_search_around, amap_search_text, score_candidates, ask_user]
