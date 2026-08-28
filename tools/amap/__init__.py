"""高德工具注册：把 AmapClient 包装成 harness 的 Tool。"""
from __future__ import annotations

from harness.tool_registry import Tool, ToolRegistry

from .client import AmapClient

__all__ = ["AmapClient", "register_amap_tools"]


class _GeocodeTool(Tool):
    name = "amap_geocode"
    description = "地理编码：自然语言地址/地标 → GCJ-02 坐标"

    def __init__(self, client: AmapClient) -> None:
        self._client = client

    def run(self, address: str, city: str | None = None):
        return self._client.geocode(address, city)


class _RegeoTool(Tool):
    name = "amap_regeo"
    description = "逆地理编码：坐标 → 结构化地址"

    def __init__(self, client: AmapClient) -> None:
        self._client = client

    def run(self, location: str, radius: int = 1000):
        return self._client.regeo(location, radius)


class _AroundTool(Tool):
    name = "amap_place_around"
    description = "周边搜索：以坐标+半径召回附近餐饮 POI（types=050000）"

    def __init__(self, client: AmapClient) -> None:
        self._client = client

    def run(self, location: str, radius: int = 5000, keywords: str | None = None,
            page: int = 1, offset: int = 20):
        return self._client.search_around(location, radius, keywords, page, offset)


class _TextTool(Tool):
    name = "amap_place_text"
    description = "文本搜索：按关键词+城市搜餐饮 POI（citylimit 严格限定城市）"

    def __init__(self, client: AmapClient) -> None:
        self._client = client

    def run(self, keywords: str, city: str | None = None, page: int = 1, offset: int = 20):
        return self._client.search_text(keywords, city, page, offset)


def register_amap_tools(registry: ToolRegistry, client: AmapClient) -> None:
    registry.register(_GeocodeTool(client))
    registry.register(_RegeoTool(client))
    registry.register(_AroundTool(client))
    registry.register(_TextTool(client))
