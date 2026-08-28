"""create_react_agent 组装：LLM 绑定工具，纯 ReAct 循环。"""
from __future__ import annotations

import warnings

from langgraph.prebuilt import ToolNode, create_react_agent

from harness.core import Harness

from .prompt import REACT_SYSTEM_PROMPT
from .state import ReactState
from .tools import build_tools


def build_graph(harness: Harness):
    # 纯 ReAct 必须有 LLM 驱动 —— 无 no-key 规则兜底（区别于 eat_agent 的优雅降级）。
    if harness.llm is None:
        raise RuntimeError(
            "eat_react 是纯 ReAct agent，必须绑定真实 LLM（无 no-key 规则落回）。"
            "请设置 ANTHROPIC_API_KEY 或 DEEPSEEK_API_KEY；跑测试请注入 ScriptedLLM。"
        )

    # handle_tool_errors=True：AMAP 配额/网络异常转 ToolMessage，让 ReAct 循环继续而非 crash
    tool_node = ToolNode(build_tools(harness), handle_tool_errors=True)

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*create_react_agent.*")
        app = create_react_agent(
            harness.llm,
            tool_node,
            prompt=REACT_SYSTEM_PROMPT,
            state_schema=ReactState,
            checkpointer=harness.session.checkpointer,
        )
    return app
