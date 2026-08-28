"""harness：通用 agent 外壳（不感知业务）。

对外契约：Config / Harness / AgentMeta / ToolRegistry / Tool。
用法见 main.py。
"""
from .config import Config
from .core import AgentMeta, Harness
from .tool_registry import Tool, ToolRegistry

__all__ = ["Config", "Harness", "AgentMeta", "Tool", "ToolRegistry"]
