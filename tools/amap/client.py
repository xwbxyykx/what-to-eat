"""高德 Web服务 API v3 client。

- 有 AMAP_KEY：真实调用 httpx（限流/退避/错误码兜底）。
- 无 AMAP_KEY：退回内置 mock 数据，闭环照常可跑。
"""
from __future__ import annotations

import threading
import time
from datetime import date
from typing import Any

import httpx

from . import mock_data
from .models import GeocodeResult, POI

AMAP_BASE = "https://restapi.amap.com"

# 本地软熔断默认值（次/天）：真正约束是高德控制台月配额（个人认证搜索组 5,000/月、
# LBS 组 150,000/月），本地软熔断只是防调试打爆一个月配额。可用 AMAP_SOFT_LIMIT 调。
_DAILY_SOFT_LIMIT = 200


class AmapClient:
    def __init__(
        self,
        key: str | None,
        default_city: str = "广州",
        soft_limit: int = _DAILY_SOFT_LIMIT,
    ) -> None:
        self._key = key
        self._default_city = default_city
        self._soft_limit = soft_limit
        self._client = httpx.Client(timeout=10.0)
        self._daily = 0
        self._day = date.today()
        self._lock = threading.Lock()

    # ---- 配额与限流 ----
    def _consume(self, n: int = 1) -> bool:
        with self._lock:
            today = date.today()
            if today != self._day:
                self._day, self._daily = today, 0
            if self._daily + n > self._soft_limit:
                return False
            self._daily += n
            return True

    def _get(self, path: str, params: dict[str, Any]) -> dict:
        if not self._consume():
            raise RuntimeError("AMAP_QUOTA_EXCEEDED: 当日调用量已达保守上限")
        params["key"] = self._key
        resp = self._client.get(AMAP_BASE + path, params=params)
        data = resp.json()
        if data.get("status") != "1":
            # 简单退避后上抛，由 locate/search 节点降级（无结果兜底），不会崩。
            # 错误码含义随官方文档版本有出入：10003 常见为配额超限、10005 常见为 IP 白名单，
            # 排查以控制台「配额管理」与当前公网 IP 为准。
            time.sleep(1.0)
            code = data.get("infocode", "?")
            info = data.get("info", "")
            raise RuntimeError(f"AMAP_ERROR {code}: {info}")
        return data

    # ---- 对外接口 ----
    def geocode(self, address: str, city: str | None = None) -> GeocodeResult | None:
        if not self._key:
            return mock_data.mock_geocode(address, self._default_city)
        params: dict[str, Any] = {"address": address}
        if city:
            params["city"] = city
        data = self._get("/v3/geocode/geo", params)
        geos = data.get("geocodes") or []
        if not geos:
            return None
        g = geos[0]
        return GeocodeResult(
            location=g.get("location", ""),
            city=g.get("city", "") or "",
            district=g.get("district", "") or "",
            formatted_address=g.get("formatted_address", "") or "",
            level=g.get("level", "") or "",
        )

    def regeo(self, location: str, radius: int = 1000) -> str | None:
        """逆地理编码：坐标 → 结构化地址（MVP 主要用于展示兜底）。"""
        if not self._key:
            return f"广州·演示地址（Mock）"
        params: dict[str, Any] = {"location": location, "radius": str(radius)}
        data = self._get("/v3/geocode/regeo", params)
        regeocode = data.get("regeocode") or {}
        return regeocode.get("formatted_address") or None

    def search_around(
        self,
        location: str,
        radius: int = 5000,
        keywords: str | None = None,
        page: int = 1,
        offset: int = 20,
    ) -> list[POI]:
        if not self._key:
            return mock_data.mock_around(location, radius, keywords)
        params: dict[str, Any] = {
            "location": location,
            "types": "050000",          # 餐饮大类：中餐/快餐/咖啡/火锅等
            "radius": str(radius),
            "sortrule": "1",            # 综合排序
            "extensions": "all",        # 才有 tel/business_area 与 biz_ext.rating/cost
            "offset": str(offset),
            "page": str(page),
        }
        if keywords:
            params["keywords"] = keywords
        data = self._get("/v3/place/around", params)
        return [POI.from_amap_v3(p) for p in data.get("pois") or []]

    def search_text(
        self,
        keywords: str,
        city: str | None = None,
        page: int = 1,
        offset: int = 20,
    ) -> list[POI]:
        if not self._key:
            return mock_data.mock_text(keywords, city or self._default_city)
        params: dict[str, Any] = {
            "keywords": keywords,
            "types": "050000",
            "extensions": "all",
            "offset": str(offset),
            "page": str(page),
        }
        if city:
            params["city"] = city
            params["citylimit"] = "true"
        data = self._get("/v3/place/text", params)
        return [POI.from_amap_v3(p) for p in data.get("pois") or []]
