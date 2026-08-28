"""Key 自检脚本：读取 .env，逐个验证高德 / Anthropic Key 是否可用，给出修复指引。

用法：
    .venv/bin/python scripts/check_keys.py

不配置任何 Key 时提示去申请；只配一个时只校验那个。全部通过即可跑真实数据。
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.config import Config  # noqa: E402

AMAP_TEST_URL = "https://restapi.amap.com/v3/geocode/geo"
AMAP_TEST_ADDR = "广州市天河区珠江新城"

# 高德错误码含义官方文档各版本有出入（尤其 10003/10005），以下按官方「Web服务错误码说明」
# 主口径整理；排查顺序固定为：① 平台是否 Web服务 ② key 是否复制完整 ③ IP 白名单 ④ 配额进度。
AMAP_ERR = {
    "10001": "用户 key 不正确或过期——回控制台重新复制；服务平台选错（非 Web服务）也报 key 类错误",
    "10002": "用户 key 非法——回控制台核对 key 状态",
    "10003": "访问已超出配额——去控制台「配额管理」看进度（个人搜索组 5,000/月）",
    "10004": "用户 IP 非法——核对当前公网出口 IP",
    "10005": "IP 白名单不匹配（INVALID_USER_IP）——设了白名单但当前公网 IP 不在内；开发期建议留空",
    "10010": "配额超限——去控制台「配额管理」确认",
    "10014": "KEY_ERR（签名/白名单问题）——开启过数字签名 sig 请核对，否则排查白名单",
    "10019": "次数限制超限——当日调用已达上限，次日恢复",
}


def _ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def _fail(msg: str) -> None:
    print(f"  ❌ {msg}")


def check_amap(key: str) -> bool:
    print("\n[1/2] 高德 Web服务 Key 校验")
    try:
        r = httpx.get(
            AMAP_TEST_URL,
            params={"address": AMAP_TEST_ADDR, "key": key},
            timeout=10,
        )
        data = r.json()
    except Exception as e:  # noqa: BLE001
        _fail(f"请求异常：{e}（网络无法访问 restapi.amap.com？）")
        return False

    if data.get("status") == "1" and data.get("info") == "OK":
        loc = (data.get("geocodes") or [{}])[0].get("location")
        _ok(f"地理编码成功，坐标 {loc}（地址：{AMAP_TEST_ADDR}）")
        return True

    code = str(data.get("infocode", ""))
    info = data.get("info", "")
    hint = AMAP_ERR.get(
        code,
        "（未收录——排查顺序：① 平台是否 Web服务 ② key 是否完整 ③ IP 白名单 ④ 控制台配额进度）",
    )
    _fail(f"高德返回 info={info!r} infocode={code} → {hint}")
    return False


ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def check_anthropic(key: str) -> bool:
    print("\n[2/2] Anthropic (Claude) API Key 校验")
    try:
        r = httpx.post(
            ANTHROPIC_URL,
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-opus-5",
                "max_tokens": 32,
                "messages": [{"role": "user", "content": "只回复两个字：正常"}],
            },
            timeout=30,
        )
    except Exception as e:  # noqa: BLE001
        _fail(f"请求异常：{e}（网络无法访问 api.anthropic.com？）")
        return False

    if r.status_code == 200:
        body = r.json()
        text = "".join(
            b.get("text", "") for b in body.get("content", []) if b.get("type") == "text"
        )
        _ok(f"模型 {body.get('model')} 回复：{text!r}")
        return True

    msg = ""
    try:
        msg = r.json().get("error", {}).get("message", "")
    except Exception:  # noqa: BLE001
        pass
    _fail(f"HTTP {r.status_code}：{msg or r.text[:200]}")
    if r.status_code in (401, 403):
        print("     → Key 无效或未通过计费校验，检查控制台 API Keys 与 Billing 设置")
    if r.status_code == 429:
        print("     → 配额/余额不足，检查 Billing credits")
    return False


def check_deepseek(key: str, base_url: str = "https://api.deepseek.com") -> bool:
    """DeepSeek 走 OpenAI 兼容接口：POST {base_url}/chat/completions。"""
    print("\n[LLM] DeepSeek (OpenAI 兼容) Key 校验")
    url = base_url.rstrip("/") + "/chat/completions"
    try:
        r = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "max_tokens": 32,
                "messages": [{"role": "user", "content": "只回复两个字：正常"}],
            },
            timeout=30,
        )
    except Exception as e:  # noqa: BLE001
        _fail(f"请求异常：{e}（网络无法访问 {base_url}？）")
        return False
    if r.status_code == 200:
        body = r.json()
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            text = "(无内容)"
        _ok(f"模型 {body.get('model', 'deepseek-chat')} 回复：{text!r}")
        return True
    msg = ""
    try:
        err = r.json().get("error", {})
        msg = err.get("message") if isinstance(err, dict) else str(err)
    except Exception:  # noqa: BLE001
        pass
    _fail(f"HTTP {r.status_code}：{msg or r.text[:200]}")
    if r.status_code in (401, 403):
        print("     → Key 无效，检查 DEEPSEEK_API_KEY / LLM_PROVIDER 与平台认证状态")
    if r.status_code == 402:
        print("     → 余额不足，去 DeepSeek 开放平台充值")
    if r.status_code == 429:
        print("     → 限流或余额不足")
    return False


def main() -> int:
    config = Config.from_env()

    print("读取 .env …")
    checks: list[tuple[str, bool]] = []

    if config.amap_key:
        checks.append(("高德", check_amap(config.amap_key)))
    else:
        print("\n[跳过] 高德 Key 为空 → 走 mock 数据")

    if config.anthropic_api_key:
        checks.append(("Anthropic", check_anthropic(config.anthropic_api_key)))
    if config.deepseek_api_key:
        checks.append(
            ("DeepSeek", check_deepseek(config.deepseek_api_key, config.deepseek_base_url))
        )
    if not config.anthropic_api_key and not config.deepseek_api_key:
        print("\n[跳过] 未配置模型 Key（ANTHROPIC_API_KEY / DEEPSEEK_API_KEY）→ 走规则抽取 + 模板推荐")

    if not checks:
        print("\n三个 Key 都是空。当前是 mock 模式，闭环可跑但拿不到真实数据。")
        print("申请指引见 KEY_GUIDE.md 或 README「获取 Key」小节。")
        return 1

    ok = all(ok for _, ok in checks)
    print(
        "\n🎉 全部校验通过，可以直接 `.venv/bin/python main.py` 跑真实数据了。"
        if ok
        else "\n⚠️ 部分校验未通过，修复后重跑本脚本。"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
