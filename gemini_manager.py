"""Single-key Gemini API client and safe request telemetry for NEURON V2."""
import asyncio
import os
import time

import aiohttp

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_COOLDOWN_SECONDS = 90
_STATE = {}
_TOTAL = {"requests": 0, "success": 0, "rate_limited": 0, "invalid": 0, "errors": 0}


def _configured_key():
    """Read exactly one key. Multi-key environment variables are intentionally ignored."""
    return os.environ.get("GEMINI_API_KEY", "").strip()


def gemini_status():
    key = _configured_key()
    now = time.monotonic()
    if not key:
        return {"configured": 0, "max_keys": 1, "keys": [], "totals": dict(_TOTAL)}
    state = _STATE.get(key, {})
    until = float(state.get("cooldown_until", 0))
    return {
        "configured": 1,
        "max_keys": 1,
        "keys": [{
            "slot": 1,
            "label": "Gemini API kaliti",
            "masked": "…" + key[-4:] if len(key) >= 4 else "****",
            "state": "cooldown" if until > now else ("disabled" if state.get("disabled") else "ready"),
            "cooldown_seconds": max(0, int(until - now)),
            "success": int(state.get("success", 0)),
            "errors": int(state.get("errors", 0)),
        }],
        "totals": dict(_TOTAL),
    }


async def gemini_generate(model, payload, timeout_seconds=100):
    """Send one request using the single configured key; never log or return the secret."""
    key = _configured_key()
    if not key:
        return None, "not_configured"

    state = _STATE.setdefault(key, {})
    now = time.monotonic()
    if state.get("disabled"):
        return None, "invalid_api_key"
    if float(state.get("cooldown_until", 0)) > now:
        return None, "rate_limited"

    timeout = aiohttp.ClientTimeout(total=timeout_seconds, connect=15)
    _TOTAL["requests"] += 1
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            url = BASE_URL.format(model=model)
            async with session.post(url, params={"key": key}, json=payload) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    state["success"] = int(state.get("success", 0)) + 1
                    _TOTAL["success"] += 1
                    state.pop("cooldown_until", None)
                    return data, "ok"
                state["errors"] = int(state.get("errors", 0)) + 1
                if response.status == 429:
                    state["cooldown_until"] = time.monotonic() + _COOLDOWN_SECONDS
                    _TOTAL["rate_limited"] += 1
                    return None, "rate_limited"
                if response.status in (401, 403):
                    state["disabled"] = True
                    _TOTAL["invalid"] += 1
                    return None, "invalid_api_key"
                if response.status >= 500:
                    state["cooldown_until"] = time.monotonic() + 20
                _TOTAL["errors"] += 1
                return None, "provider_error_" + str(response.status)
    except asyncio.TimeoutError:
        state["cooldown_until"] = time.monotonic() + 20
        state["errors"] = int(state.get("errors", 0)) + 1
        _TOTAL["errors"] += 1
        return None, "timeout"
    except Exception:
        state["cooldown_until"] = time.monotonic() + 20
        state["errors"] = int(state.get("errors", 0)) + 1
        _TOTAL["errors"] += 1
        return None, "network_error"
