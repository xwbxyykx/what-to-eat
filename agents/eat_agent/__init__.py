"""eat_agent：可插拔的 LangGraph 吃饭推荐 agent。"""
from __future__ import annotations

from harness.config import Config

from .graph import build_graph


def start_state(config: Config) -> dict:
    return {
        "raw_input": "",
        "requirement": {},
        "clarify_needed": False,
        "clarify_count": 0,
        "clarification_history": [],
        "location_desc": None,
        "location": None,
        "city": None,
        "radius": config.default_radius,
        "location_source": "",
        "candidates": [],
        "scored": [],
        "top_k": [],
        "final_answer": {},
        "search_hint": None,
        "no_result": False,
        "continuation_intent": False,
        "dedupe_note": None,
        "messages": [],
    }


__all__ = ["build_graph", "start_state"]
