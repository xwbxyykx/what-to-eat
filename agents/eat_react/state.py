"""ReAct 图状态：最小化，只保留对话消息 + create_react_agent 要求的 remaining_steps。

刻意回避 eat_agent 的 operator.add 累积字段：ReAct 里工具输出写回 messages（add_messages 追加），
业务候选/打分若用 reducer 累积会跨轮残留（见 eat_agent/core.py 的落地雷注释），这里保持最小状态。
"""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from langgraph.managed import RemainingSteps
from typing_extensions import NotRequired


class ReactState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    remaining_steps: NotRequired[RemainingSteps]
