"""LangGraph 组装：6 节点 + 条件路由 + checkpointer 编译。"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from harness.core import Harness

from .memory import ConversationMemory
from .nodes.clarify import clarify_node
from .nodes.extract import extract_node
from .nodes.locate import locate_node
from .nodes.recommend import recommend_node
from .nodes.score import score_node
from .nodes.search import search_node
from .routing import build_routers
from .state import ReqState


def build_graph(harness: Harness):
    config = harness.config
    registry = harness.tools
    llm = harness.llm
    routers = build_routers(config)

    # 一次 run() 即一段对话：memory 放在 graph 闭包里，跨轮次携带上下文。
    # harness.run() 只 build 一次 app 并复用整个输入循环，故 memory 天然存活一轮对话。
    memory = ConversationMemory()

    builder = StateGraph(ReqState)

    builder.add_node("extract", extract_node(llm, memory))
    builder.add_node("clarify", clarify_node())
    builder.add_node("locate", locate_node(registry, config))
    builder.add_node("search", search_node(registry, config))
    builder.add_node("score", score_node(config, memory))
    builder.add_node("recommend", recommend_node(llm, memory))

    builder.add_edge(START, "extract")
    builder.add_conditional_edges(
        "extract",
        routers["after_extract"],
        {"clarify": "clarify", "locate": "locate"},
    )
    builder.add_edge("clarify", "extract")
    builder.add_conditional_edges(
        "locate",
        routers["after_locate"],
        {"clarify": "clarify", "search": "search"},
    )
    builder.add_conditional_edges(
        "search",
        routers["after_search"],
        {"score": "score", "end": END},
    )
    builder.add_edge("score", "recommend")
    builder.add_edge("recommend", END)

    return builder.compile(checkpointer=harness.session.checkpointer)
