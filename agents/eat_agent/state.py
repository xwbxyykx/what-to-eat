"""State 定义：结构化抽取结果 Requirement + 图状态 ReqState。"""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class Requirement(BaseModel):
    """用户需求的结构化槽位（LLM 抽取结果）。"""

    intent: str = "找餐厅"
    cuisine: list[str] = Field(default_factory=list)       # 菜系
    dish: list[str] = Field(default_factory=list)          # 菜品
    taste: list[str] = Field(default_factory=list)         # 口味
    location_desc: str | None = None                       # 位置描述（交高德 geocode）
    budget_preference: str | None = None                   # 便宜 / 中档 / 贵
    party_size: int | None = None
    scenario: str | None = None                            # 一人食/聚餐/约会/商务
    dining_time: str | None = None                         # 午餐/晚餐/夜宵
    dietary: list[str] = Field(default_factory=list)       # 忌口/饮食限制
    rating_threshold: float | None = None
    clarify_needed: bool = False
    missing_required_slots: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)


class ReqState(TypedDict, total=False):
    """图状态。纪律：累积列表用 Annotated[list, operator.add]，当前值用裸类型覆盖。"""

    raw_input: str
    requirement: dict
    clarify_needed: bool
    clarify_count: int
    clarification_history: Annotated[list[str], operator.add]
    location_desc: str | None
    location: str | None                                    # "lng,lat"（GCJ-02）
    city: str | None
    radius: int
    location_source: str                                    # "user" | "default" | "error"
    candidates: Annotated[list[dict], operator.add]         # 各次召回累积（规范化 POI）
    scored: Annotated[list[dict], operator.add]             # 候选 + score + breakdown
    top_k: list[dict]
    final_answer: dict
    search_hint: str | None
    no_result: bool
    messages: Annotated[list[AnyMessage], add_messages]     # 多轮预留
    continuation_intent: bool                               # 本轮是否「换一家/再来一家」类延续意图
    dedupe_note: str | None                                 # 去重耗尽时的诚实提示（score 写，recommend 渲染）
