# -*- coding: utf-8 -*-
"""Quick check: --force-notify bypasses 24h dedupe for close_confirm_stop."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src_scripts"))
os.environ["TWSTOCKALS_WORKSPACE"] = ROOT

from notify import already_sent, mark_sent, notify  # noqa: E402


def main() -> int:
    symbol, rule_id = "MARKET", "close_confirm_stop"
    mark_sent(symbol, rule_id, urgency="emergency")
    assert already_sent(symbol, rule_id), "expected dedupe hit after mark_sent"

    skipped = notify(
        title="dedupe-should-skip",
        body="should not send",
        symbol=symbol,
        rule_id=rule_id,
        urgency="emergency",
        force=False,
        dry_run=True,
    )
    assert skipped is False, "without force, notify must skip when deduped"

    sent = notify(
        title="force-should-send",
        body="force bypass dry-run ok",
        symbol=symbol,
        rule_id=rule_id,
        urgency="emergency",
        force=True,
        dry_run=True,
    )
    assert sent is True, "with force=True, notify must proceed even if deduped"

    # Mirror scan_black_swan argv contract
    sys.argv = ["scan_black_swan.py", "--force-notify"]
    force_flag = "--force-notify" in sys.argv
    assert force_flag is True
    print("OK: force-notify bypasses dedupe (dry-run)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
