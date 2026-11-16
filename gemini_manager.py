"""Secure Gemini API-key rotation and request telemetry for NEURON V2."""
import asyncio
import json
import logging
import os
import time

import aiohttp

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_KEYS = 10
_COOLDOWN_SECONDS = 90
_LOCK = asyncio.Lock()
_CURSOR = 0
_STATE = {}
_TOTAL = {"requests": 0, "success": 0, "rate_limited": 0, "invalid": 0, "errors": 0}


def _configured_keys():
    raw = os.environ.get("GEMINI_API_KEYS", "")
    values = []
    # Accept either newline/comma separated keys or a JSON array.
    try:
        parsed = json.loads(raw) if raw.strip().startswith("[") else None
    except Exception:
        parsed = None
    if isinstance(parsed, list):
        values.extend(str(x).strip() for x in parsed)
    else:
        values.extend(x.strip() for x in raw.replace("\r", "\n").replace(",", "\n").splitlines())
    single = os.environ.get("GEMINI_API_KEY", "").strip()
    if single:
        values.append(single)
    unique = []
    for value in values:
        if value and value not in unique:
            unique.append(value)
    return unique[:MAX_KEYS]


def gemini_status():
    keys = _configured_keys()
    now = time.monotonic()
    items = []
    for index, key in enumerate(keys):
        state = _STATE.get(key, {})
        until = float(state.get("cooldown_until", 0))
        items.append({
            "slot": index + 1,
            "label": "Kalit " + str(index + 1),
            "masked": "…" + key[-4:] if len(key) >= 4 else "****",
            "state": "cooldown" if until > now else ("disabled" if state.get("disabled") else "ready"),
            "cooldown_seconds": max(0, int(until - now)),
            "success": int(state.get("success", 0)),
            "errors": int(state.get("errors", 0)),
        })
    return {
        "configured": len(keys),
        "max_keys": MAX_KEYS,
        "keys": items,
        "totals": dict(_TOTAL),
    }


async def gemini_generate(model, payload, timeout_seconds=100):
    """Try configured keys in rotation; secrets are never returned or logged."""
    global _CURSOR
    keys = _configured_keys()
    if not keys:
        return None, "not_configured"
    now = time.monotonic()
    async with _LOCK:
        start = _CURSOR % len(keys)
        ordered = keys[start:] + keys[:start]
        _CURSOR = (start + 1) % len(keys)
    attempted = 0
    last_status = "provider_error"
    timeout = aiohttp.ClientTimeout(total=timeout_seconds, connect=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for key in ordered:
            state = _STATE.setdefault(key, {})
            if state.get("disabled") or float(state.get("cooldown_until", 0)) > now:
                continue
            attempted += 1
            _TOTAL["requests"] += 1
            try:
                url = BASE_URL.format(model=model)
                async with session.post(url, params={"key": key}, json=payload) as response:
                    if response.status == 200:
                        data = await response.json(content_type=None)
                        state["success"] = int(state.get("success", 0)) + 1
                        _TOTAL["success"] += 1
                        return data, "ok"
                    if response.status == 429:
                        state["cooldown_until"] = time.monotonic() + _COOLDOWN_SECONDS
                        state["errors"] = int(state.get("errors", 0)) + 1
                        _TOTAL["rate_limited"] += 1
                        last_status = "rate_limited"
                        continue
                    if response.status in (400, 401, 403):
                        # A 400 can be a model/request issue, so don't permanently disable the key.
                        if response.status in (401, 403):
                            state["disabled"] = True
                            _TOTAL["invalid"] += 1
                            last_status = "invalid_api_key"
                        else:
                            last_status = "provider_error_400"
                        state["errors"] = int(state.get("errors", 0)) + 1
                        continue
                    state["cooldown_until"] = time.monotonic() + 20
                    state["errors"] = int(state.get("errors", 0)) + 1
                    _TOTAL["errors"] += 1
                    last_status = "provider_error_" + str(response.status)
            except asyncio.TimeoutError:
                state["cooldown_until"] = time.monotonic() + 20
                state["errors"] = int(state.get("errors", 0)) + 1
                _TOTAL["errors"] += 1
                last_status = "timeout"
            except Exception:
                state["cooldown_until"] = time.monotonic() + 20
                state["errors"] = int(state.get("errors", 0)) + 1
                _TOTAL["errors"] += 1
                last_status = "network_error"
    if attempted == 0 and any(state.get("disabled") for state in _STATE.values()):
        return None, "no_usable_keys"
    return None, last_status
