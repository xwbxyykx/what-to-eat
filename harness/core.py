"""Harness 主类：装配 config / llm / tools / session / io，驱动注册的 agent。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

import structlog

from langchain_core.messages import AIMessage, HumanMessage

from .config import Config
from .io import CLI, run_graph_with_interrupts
from .llm_client import build_chat_llm
from .session import SessionManager
from .tool_registry import ToolRegistry

log = structlog.get_logger(__name__)


@dataclass
class AgentMeta:
    """可插拔 agent 的注册描述。"""

    name: str
    description: str
    # build_graph(harness) -> 编译后的 LangGraph Runnable
    build_graph: Callable[["Harness"], Any]
    # start_state(config) -> 图的初始 state
    start_state: Callable[[Config], dict]
    # run_mode: "per_turn_thread"（每轮全新 thread，eat_agent 默认）| "session_thread"（稳定 thread，ReAct 记忆）
    run_mode: str = "per_turn_thread"


class Harness:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config.from_env()
        self.tools = ToolRegistry()
        self.session = SessionManager(self.config)
        self.llm = build_chat_llm(self.config)
        self._agents: dict[str, AgentMeta] = {}

    def register_tool(self, tool: Any) -> None:
        self.tools.register(tool)

    def register_agent(self, meta: AgentMeta) -> None:
        self._agents[meta.name] = meta
        log.info("agent_registered", name=meta.name)

    def run(self, agent_name: str = "eat") -> None:
        meta = self._agents[agent_name]
        app = meta.build_graph(self)
        cli = CLI()

        cli.say(f"[harness] agent: {meta.name} — {meta.description}")
        cli.say(
            f"[harness] 高德: {'mock 数据' if self.config.use_mock_amap else '真实 API'}"
            f" | LLM: {_llm_label(self.config)}"
        )
        cli.say("输入吃饭需求后回车（如「想吃辣的，人均100以内，天河附近」），输入 exit 退出。")

        if meta.run_mode == "session_thread":
            self._run_session_thread(meta, app, cli)
            return
        self._run_per_turn_thread(meta, app, cli)

    def _run_per_turn_thread(self, meta: AgentMeta, app: Any, cli: CLI) -> None:
        counter = 0
        seen_threads: set[str] = set()
        while True:
            text = cli.prompt("需求")
            if not text or text in ("exit", "quit", "q"):
                break
            counter += 1
            # 【不变量】每轮全新 thread_id，绝不跨轮复用。
            # 因为 candidates/scored/clarification_history 是 operator.add reducer、
            # messages 是 add_messages —— 复用同一 thread 会让旧状态累积进下一轮，
            # 并把上一轮的 requirement/top_k 带进来。多轮上下文走 graph 闭包里的
            # ConversationMemory，不需要（也不允许）复用 thread。若未来有人想改回
            # "按用户复用 thread"，必须先审慎评估 reducer 累积，此处用断言语义挡住。
            thread = self.session.thread_id(f"local-{os.getpid()}-{counter}")
            assert thread not in seen_threads, "thread_id 必须每轮唯一，禁止跨轮复用"
            seen_threads.add(thread)
            initial = meta.start_state(self.config)
            initial["raw_input"] = text
            result = run_graph_with_interrupts(app, cli, initial, thread)
            self._report(cli, result)

    def _run_session_thread(self, meta: AgentMeta, app: Any, cli: CLI) -> None:
        """ReAct 会话：稳定 thread 保留 messages 历史，跨轮继承上下文、避免重复推荐。"""
        thread = self.session.thread_id(f"session-{os.getpid()}")
        while True:
            text = cli.prompt("需求")
            if not text or text in ("exit", "quit", "q"):
                break
            result = run_graph_with_interrupts(
                app, cli, {"messages": [HumanMessage(text)]}, thread
            )
            self._report_react(cli, result)

    @staticmethod
    def _report_react(cli: CLI, result: dict | None) -> None:
        """ReAct agent 的输出是最后一条 assistant 消息，而非结构化 final_answer。"""
        msgs = (result or {}).get("messages") or []
        last = msgs[-1] if msgs else None
        content = ""
        if isinstance(last, AIMessage):
            c = last.content
            if isinstance(c, str):
                content = c
            elif isinstance(c, list):  # 多模态 content blocks
                parts = [
                    (b.get("text", "") if isinstance(b, dict) else str(b)) for b in c
                ]
                content = " ".join(parts)
            else:
                content = str(c)
        if content.strip():
            cli.say(content.strip())
        else:
            cli.say("抱歉，这次没有合适的推荐。")

    @staticmethod
    def _report(cli: CLI, result: dict) -> None:
        final = result.get("final_answer") if isinstance(result, dict) else None
        if final:
            cli.say(cli.render_final(final))
        elif result.get("search_hint"):
            cli.say(result["search_hint"])
        else:
            cli.say("抱歉，这次没有找到合适的推荐，换种说法再试试？")


def _llm_label(config: Config) -> str:
    """横幅上显示实际生效的模型层，避免误导（config.model 只是默认值，可能被 provider 覆盖）。"""
    if config.use_mock_llm:
        return "mock 规则"
    if config.resolved_llm_provider == "deepseek":
        return f"DeepSeek ({config.deepseek_model})"
    return f"Claude ({config.model})"
