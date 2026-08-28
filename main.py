"""CLI 入口：装配 harness + 注册高德工具 + 注册 eat / eat_react + run。

通过 `python main.py [agent]`（或环境变量 AGENT）选择 agent，默认 eat_react。
"""
from __future__ import annotations

import os
import sys

import structlog

from agents.eat_agent import build_graph as eat_build_graph
from agents.eat_agent import start_state as eat_start_state
from agents.eat_react import build_graph as react_build_graph
from agents.eat_react import start_state as react_start_state
from harness.config import Config
from harness.core import AgentMeta, Harness
from harness.logging_tracing import setup_logging
from tools.amap import AmapClient, register_amap_tools

log = structlog.get_logger(__name__)


def main() -> None:
    config = Config.from_env()
    setup_logging(config.log_level, config.langsmith_enabled)

    harness = Harness(config)
    client = AmapClient(
        config.amap_key,
        default_city=config.default_city,
        soft_limit=config.amap_soft_limit,
    )
    register_amap_tools(harness.tools, client)

    harness.register_agent(
        AgentMeta(
            name="eat",
            description="确定性 LangGraph 推荐 agent",
            build_graph=eat_build_graph,
            start_state=eat_start_state,
        )
    )
    harness.register_agent(
        AgentMeta(
            name="eat_react",
            description="纯 ReAct 工具驱动 agent",
            build_graph=react_build_graph,
            start_state=react_start_state,
            run_mode="session_thread",
        )
    )

    agent = sys.argv[1] if len(sys.argv) > 1 else os.getenv("AGENT", "eat_react")
    # eat_react 是纯 ReAct agent，必须用真实 LLM 驱动；无 key 时明确报错而非静默降级。
    if agent == "eat_react" and config.resolved_llm_provider == "mock":
        log.error(
            "eat_react 需要真实 LLM 驱动（纯 ReAct 无 no-key 规则兜底）；当前未配置任何 key。"
            "请设置 ANTHROPIC_API_KEY 或 DEEPSEEK_API_KEY，或用 `python main.py eat` 走确定性 agent。"
        )
        raise SystemExit(2)

    try:
        harness.run(agent)
    except RuntimeError as exc:
        log.error("agent_start_failed", agent=agent, error=str(exc))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
