"""ConversationMemory：跨轮次携带上一轮需求/位置/已推荐，供下一轮继承与去重。

放在 graph 闭包里（build_graph 创建一次），一次 run() 即一段对话。
纯 Python 对象，不依赖 checkpointer、不进入状态通道 —— 避免 operator.add 跨轮累积污染。
"""
from __future__ import annotations

from dataclasses import dataclass, field


def poi_key(candidate: dict) -> str:
    """POI 去重键：优先 name|location（lng,lat 恒定且唯一），回退 name|address。

    绝不塌缩成裸 name：同名连锁店（真实高德 address 常为空）会互相误判。
    """
    name = (candidate.get("name") or "").strip()
    location = (candidate.get("location") or "").strip()
    if location:
        return f"{name}|{location}"
    address = (candidate.get("address") or "").strip()
    if address:
        return f"{name}|{address}"
    return f"{name}|__noaddr__"


@dataclass
class ConversationMemory:
    """一次 run() 内跨轮次的对话记忆。只在图走到底（产出推荐）后回写。"""

    prev_requirement: dict | None = None      # 上一轮最终结构化需求（含 location_desc）
    prev_city: str | None = None              # 上一轮定位城市（locate 节点产出）
    prev_location: str | None = None          # 上一轮定位坐标 "lng,lat"（预留）
    prev_recommended_keys: list[str] = field(default_factory=list)  # 仅上一轮 top-K 的去重键

    def record(self, state: dict) -> None:
        """一轮图跑完后回写。无结果/空推荐时不清空 —— 避免丢上一轮去重集与位置。

        prev_city / prev_location 取自 state（locate 节点设置），而非 requirement，
        因为默认城市/澄清耗尽时 requirement.location_desc 会保持 None。
        """
        items = (state.get("final_answer") or {}).get("items") or []
        top_k = state.get("top_k") or []
        if not top_k or not items:
            return
        self.prev_requirement = state.get("requirement")
        self.prev_city = state.get("city")
        self.prev_location = state.get("location")
        self.prev_recommended_keys = [poi_key(sc["candidate"]) for sc in top_k]


__all__ = ["ConversationMemory", "poi_key"]
