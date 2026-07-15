# -*- coding: utf-8 -*-
"""Taiwan local time (UTC+8) for alerts — never rely on runner/OS local TZ."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

TW = ZoneInfo("Asia/Taipei")


def taiwan_now() -> datetime:
    """Aware datetime in Asia/Taipei (UTC+8)."""
    return datetime.now(TW)


def taiwan_hhmm() -> str:
    return taiwan_now().strftime("%H%M")


def taiwan_stamp(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return taiwan_now().strftime(fmt)
