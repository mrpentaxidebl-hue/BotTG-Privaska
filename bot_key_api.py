"""
Модуль для связи Telegram-бота BlackDLC с Key Server.
Использование: импортируй в main.py и вызывай generate_key / block_key.
"""

import os
import urllib.request
import urllib.error
import json

# URL твоего Key Server (после деплоя на Replit/Render замени)
KEY_SERVER_URL = os.environ.get("KEY_SERVER_URL", "http://localhost:3000")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "BH-ADMIN-OWNER2025")

# Маппинг тарифов бота → тип ключа на сервере
PLAN_TO_TYPE = {
    0: "7D",   # 7 дней
    1: "30D",  # 30 дней
    2: "60D",  # 60 дней
    3: "LT",   # Навсегда
}


def _request(method: str, path: str, body: dict | None = None) -> dict:
    url = KEY_SERVER_URL.rstrip("/") + path
    data = None
    headers = {"Content-Type": "application/json", "X-Admin-Key": ADMIN_KEY}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def generate_key(plan_index: int = 0, count: int = 1) -> dict:
    """
    Генерирует ключ(и) на сервере.
    plan_index: 0=7D, 1=30D, 2=60D, 3=LT
    Возвращает: {"ok": True, "keys": ["BH-7D-XXXXXX", ...]}
    """
    key_type = PLAN_TO_TYPE.get(plan_index, "7D")
    return _request("POST", "/api/admin/keys/generate", {
        "type": key_type,
        "count": count,
        "adminKey": ADMIN_KEY,
    })


def generate_key_by_type(key_type: str, count: int = 1) -> dict:
    """key_type: '7D' | '30D' | '60D' | 'LT'"""
    return _request("POST", "/api/admin/keys/generate", {
        "type": key_type,
        "count": count,
        "adminKey": ADMIN_KEY,
    })


def block_key(key: str) -> dict:
    return _request("POST", "/api/admin/keys/block", {
        "key": key,
        "adminKey": ADMIN_KEY,
    })


def unblock_key(key: str) -> dict:
    return _request("POST", "/api/admin/keys/unblock", {
        "key": key,
        "adminKey": ADMIN_KEY,
    })


def list_keys() -> dict:
    return _request("GET", f"/api/keys?adminKey={ADMIN_KEY}")
