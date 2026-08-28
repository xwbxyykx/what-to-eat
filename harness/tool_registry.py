"""工具注册表：注册确定性工具，统一调用入口（限流/退避由具体客户端承担）。"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Any

import structlog

log = structlog.get_logger(__name__)


class Tool(ABC):
    name: str = ""
    description: str = ""

    @abstractmethod
    def run(self, **params: Any) -> Any:
        """执行工具。参数以 kwargs 传入，返回规范化结果。"""


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._lock = threading.Lock()

    def register(self, tool: Tool) -> None:
        with self._lock:
            self._tools[tool.name] = tool
        log.info("tool_registered", name=tool.name)

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def call(self, name: str, **params: Any) -> Any:
        tool = self._tools[name]
        try:
            result = tool.run(**params)
            log.info("tool_call", name=name, ok=True)
            return result
        except Exception as exc:  # noqa: BLE001 —— 工具异常统一上抛给节点处理
            log.error("tool_call_failed", name=name, error=str(exc))
            raise

    def names(self) -> list[str]:
        return list(self._tools)
