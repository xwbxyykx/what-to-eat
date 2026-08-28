"""会话持久化：LangGraph checkpointer（Sqlite 文件） + thread_id 多会话隔离。"""
from __future__ import annotations

import sqlite3

import structlog
from langgraph.checkpoint.sqlite import SqliteSaver

from .config import Config

log = structlog.get_logger(__name__)


class SessionManager:
    def __init__(self, config: Config) -> None:
        self.config = config
        path = config.resolve_db_path()
        # 直接持有 sqlite3.Connection 构造 saver（from_conn_string 是 contextmanager，
        # 应用长驻场景用直接构造更合适）
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._checkpointer = SqliteSaver(self._conn)
        self._checkpointer.setup()  # 幂等建表
        log.info("session_ready", db=str(path))

    @property
    def checkpointer(self) -> SqliteSaver:
        return self._checkpointer

    @staticmethod
    def thread_id(user: str = "local") -> str:
        return f"user-{user}"
