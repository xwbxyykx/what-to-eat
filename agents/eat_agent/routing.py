"""条件路由：路由函数只读 state 返回路由键；path_map 必须覆盖所有返回值。"""
from __future__ import annotations

from typing import Callable

from harness.config import Config

from .state import ReqState


def make_route_after_extract(max_rounds: int) -> Callable[[ReqState], str]:
    def route(state: ReqState) -> str:
        if state.get("clarify_needed") and state.get("clarify_count", 0) < max_rounds:
            return "clarify"
        return "locate"

    return route


def make_route_after_locate() -> Callable[[ReqState], str]:
    def route(state: ReqState) -> str:
        if state.get("location_source") == "error":
            return "clarify"
        return "search"

    return route


def make_route_after_search() -> Callable[[ReqState], str]:
    def route(state: ReqState) -> str:
        if state.get("no_result"):
            return "end"
        return "score"

    return route


def build_routers(config: Config):
    return {
        "after_extract": make_route_after_extract(config.max_clarify_rounds),
        "after_locate": make_route_after_locate(),
        "after_search": make_route_after_search(),
    }
