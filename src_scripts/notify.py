# -*- coding: utf-8 -*-
"""Telegram + Email notification helper with dedupe state."""
from __future__ import annotations

import json
import os
import smtplib
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from typing import Optional

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WORKSPACE = os.environ.get(
    "TWSTOCKALS_WORKSPACE",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
)
API_KEYS_PATH = os.path.join(WORKSPACE, "config", "api_keys.json")
ALERT_RULES_PATH = os.path.join(WORKSPACE, "config", "alert_rules.json")
ALERT_STATE_PATH = os.path.join(WORKSPACE, "reports", "alert_state.json")
NOTIFY_BATCH_PATH = os.path.join(WORKSPACE, "reports", "notify_batch_pending.json")

sys.path.insert(0, os.path.join(WORKSPACE, "src_scripts"))
from tw_time import taiwan_now  # noqa: E402


def _now() -> datetime:
    """Naive Taipei wall-clock for dedupe keys / timestamps (cloud-safe)."""
    return taiwan_now().replace(tzinfo=None)


def _load_json(path: str, default=None):
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_notify_config() -> dict:
    """Merge api_keys.json with environment variables (GitHub Secrets / local .env)."""
    cfg = _load_json(API_KEYS_PATH, {})
    env_map = {
        "TELEGRAM_BOT_TOKEN": "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID": "TELEGRAM_CHAT_ID",
        "SMTP_HOST": "SMTP_HOST",
        "SMTP_PORT": "SMTP_PORT",
        "SMTP_USER": "SMTP_USER",
        "SMTP_PASSWORD": "SMTP_PASSWORD",
        "SMTP_TO": "SMTP_TO",
        "NOTIFY_DRY_RUN": "NOTIFY_DRY_RUN",
        "GEMINI_API_KEY": "GEMINI_API_KEY",
    }
    for key, env_name in env_map.items():
        val = os.environ.get(env_name)
        if val is not None and str(val).strip() != "":
            if key == "SMTP_PORT":
                try:
                    cfg[key] = int(val)
                except ValueError:
                    cfg[key] = val
            elif key == "NOTIFY_DRY_RUN":
                cfg[key] = str(val).strip().lower() in ("1", "true", "yes", "y")
            else:
                cfg[key] = val
    # Cloud default: if telegram token comes from env and DRY_RUN unset, send for real
    if os.environ.get("TWSTOCKALS_CLOUD") == "1" and "NOTIFY_DRY_RUN" not in os.environ:
        if cfg.get("TELEGRAM_BOT_TOKEN"):
            cfg["NOTIFY_DRY_RUN"] = False
    return cfg


def load_alert_rules() -> dict:
    return _load_json(ALERT_RULES_PATH, {})


def _load_state() -> dict:
    return _load_json(ALERT_STATE_PATH, {"sent": {}})


def _save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(ALERT_STATE_PATH), exist_ok=True)
    with open(ALERT_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _dedupe_key(symbol: str, rule_id: str, day: Optional[str] = None) -> str:
    day = day or _now().strftime("%Y-%m-%d")
    return f"{day}|{symbol}|{rule_id}"


def already_sent(symbol: str, rule_id: str, cooldown_hours: Optional[float] = None) -> bool:
    rules = load_alert_rules()
    if cooldown_hours is None:
        cooldown_hours = float(rules.get("cooldown_hours", 24))
    state = _load_state()
    key = _dedupe_key(symbol, rule_id)
    entry = state.get("sent", {}).get(key)
    if not entry:
        # also accept any key with same symbol+rule within cooldown window
        cutoff = _now() - timedelta(hours=cooldown_hours)
        for k, v in state.get("sent", {}).items():
            parts = k.split("|")
            if len(parts) >= 3 and parts[1] == symbol and parts[2] == rule_id:
                try:
                    ts = datetime.fromisoformat(v.get("ts", ""))
                    if ts.tzinfo is not None:
                        ts = ts.astimezone(taiwan_now().tzinfo).replace(tzinfo=None)
                    if ts >= cutoff:
                        return True
                except ValueError:
                    continue
        return False
    try:
        ts = datetime.fromisoformat(entry.get("ts", ""))
        if ts.tzinfo is not None:
            ts = ts.astimezone(taiwan_now().tzinfo).replace(tzinfo=None)
        return _now() - ts < timedelta(hours=cooldown_hours)
    except ValueError:
        return True


def mark_sent(symbol: str, rule_id: str, urgency: str = "eod_action") -> None:
    state = _load_state()
    state.setdefault("sent", {})
    key = _dedupe_key(symbol, rule_id)
    state["sent"][key] = {
        "ts": _now().isoformat(timespec="seconds"),
        "urgency": urgency,
    }
    # prune older than 14 days
    cutoff = _now() - timedelta(days=14)
    pruned = {}
    for k, v in state["sent"].items():
        try:
            ts = datetime.fromisoformat(v.get("ts", ""))
            if ts.tzinfo is not None:
                ts = ts.astimezone(taiwan_now().tzinfo).replace(tzinfo=None)
            if ts >= cutoff:
                pruned[k] = v
        except ValueError:
            continue
    state["sent"] = pruned
    _save_state(state)


def _ssl_context():
    """Prefer certifi CA bundle (helps Windows / corporate MITM chains)."""
    import ssl

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def send_telegram(text: str, dry_run: Optional[bool] = None) -> bool:
    cfg = load_notify_config()
    if dry_run is None:
        dry_run = bool(cfg.get("NOTIFY_DRY_RUN", True))
    token = (cfg.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = str(cfg.get("TELEGRAM_CHAT_ID") or "").strip()
    if dry_run or not token or not chat_id:
        print(f"[notify/telegram dry-run] {text[:200]}{'...' if len(text) > 200 else ''}")
        return dry_run or False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }
    # Prefer requests (better SSL / proxy behavior on Windows)
    try:
        import requests

        resp = requests.post(url, data=data, timeout=15)
        if resp.status_code == 200:
            return True
        print(f"[notify/telegram error] HTTP {resp.status_code}")
        return False
    except Exception as e_req:
        payload = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(url, data=payload, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15, context=_ssl_context()) as resp:
                return resp.status == 200
        except Exception as e:
            print(f"[notify/telegram error] requests={e_req}; urllib={e}")
            return False


def send_email(subject: str, body: str, dry_run: Optional[bool] = None) -> bool:
    cfg = load_notify_config()
    if dry_run is None:
        dry_run = bool(cfg.get("NOTIFY_DRY_RUN", True))
    host = (cfg.get("SMTP_HOST") or "smtp.gmail.com").strip()
    port = int(cfg.get("SMTP_PORT") or 587)
    user = (cfg.get("SMTP_USER") or "").strip()
    password = (cfg.get("SMTP_PASSWORD") or "").strip()
    to_addr = (cfg.get("SMTP_TO") or user).strip()
    if dry_run or not user or not password or not to_addr:
        print(f"[notify/email dry-run] subject={subject} body={body[:200]}{'...' if len(body) > 200 else ''}")
        return dry_run or False
    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr
    try:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(user, [to_addr], msg.as_string())
        return True
    except Exception as e:
        print(f"[notify/email error] {e}")
        return False


def _batch_enabled() -> bool:
    return os.environ.get("TWSTOCKALS_BATCH_NOTIFY", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "y",
    )


def _append_batch_item(
    title: str,
    body: str,
    *,
    symbol: str,
    rule_id: str,
    urgency: str,
) -> None:
    state = _load_json(NOTIFY_BATCH_PATH, {"items": []})
    state.setdefault("items", []).append(
        {
            "ts": _now().isoformat(timespec="seconds"),
            "title": title,
            "body": body,
            "symbol": symbol,
            "rule_id": rule_id,
            "urgency": urgency,
        }
    )
    os.makedirs(os.path.dirname(NOTIFY_BATCH_PATH), exist_ok=True)
    with open(NOTIFY_BATCH_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def clear_notify_batch() -> None:
    if os.path.exists(NOTIFY_BATCH_PATH):
        os.remove(NOTIFY_BATCH_PATH)


def flush_notify_batch(
    title: str,
    *,
    force: bool = False,
    dry_run: Optional[bool] = None,
) -> bool:
    """Merge pending batch items into one Telegram/Email."""
    state = _load_json(NOTIFY_BATCH_PATH, {"items": []})
    items = state.get("items") or []
    if not items:
        print("[notify] batch empty, nothing to flush")
        return False

    emergency = [x for x in items if x.get("urgency") == "emergency"]
    normal = [x for x in items if x.get("urgency") != "emergency"]
    parts: list[str] = []
    if emergency:
        parts.append("🚨 緊急")
        for i, it in enumerate(emergency, 1):
            parts.append(f"{i}. {it.get('title', '')}")
            parts.append(str(it.get("body", "")).strip())
            parts.append("")
    if normal:
        parts.append("📋 收盤後／觀測")
        for i, it in enumerate(normal, 1):
            parts.append(f"{i}. {it.get('title', '')}")
            parts.append(str(it.get("body", "")).strip())
            parts.append("")

    body = "\n".join(parts).strip()
    ok = notify(
        title=title,
        body=body[:3500],
        symbol="BATCH",
        rule_id="batch_digest",
        urgency="emergency" if emergency else "eod_action",
        force=force,
        dry_run=dry_run,
    )
    clear_notify_batch()
    return ok


def notify(
    title: str,
    body: str,
    *,
    symbol: str = "SYSTEM",
    rule_id: str = "generic",
    urgency: str = "eod_action",
    force: bool = False,
    dry_run: Optional[bool] = None,
) -> bool:
    """
    Send Telegram + Email. Returns True if at least one channel attempted/succeeded
    (including dry-run). Skips when deduped unless force=True.

    When TWSTOCKALS_BATCH_NOTIFY=1, queues for flush_notify_batch() instead of sending.
    """
    if _batch_enabled():
        _append_batch_item(title, body, symbol=symbol, rule_id=rule_id, urgency=urgency)
        print(f"[notify] batched {symbol}|{rule_id}: {title[:60]}")
        return True

    if not force and already_sent(symbol, rule_id):
        print(f"[notify] skip deduped {symbol}|{rule_id}")
        return False

    urgency_tag = "🚨緊急" if urgency == "emergency" else "📋收盤後執行"
    text = f"[{urgency_tag}] {title}\n\n{body}"
    if urgency == "emergency":
        text += "\n\n（建議：非破產級風險可等 13:40 後或隔日開盤處理）"

    ok_tg = send_telegram(text, dry_run=dry_run)
    ok_em = send_email(title, text, dry_run=dry_run)
    if ok_tg or ok_em:
        mark_sent(symbol, rule_id, urgency=urgency)
        return True
    return False


if __name__ == "__main__":
    notify(
        "通知測試",
        "這是 twstockals notify.py 測試訊息。若看到 dry-run 表示尚未填入 Telegram/SMTP 金鑰。",
        symbol="TEST",
        rule_id="self_test",
        urgency="eod_action",
        force=True,
    )
