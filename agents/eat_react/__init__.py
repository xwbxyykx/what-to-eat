"""eat_react：纯 ReAct 工具驱动 agent（与 eat_agent 并存）。"""
from __future__ import annotations

from harness.config import Config

from .build import build_graph


def start_state(config: Config) -> dict:
    # session_thread 模式下 run() 不调用 start_state；此处仅为满足 AgentMeta 签名。
    # create_react_agent 每次以 {"messages": [HumanMessage(...)]} 作为输入。
    return {"messages": []}


__all__ = ["build_graph", "start_state"]
