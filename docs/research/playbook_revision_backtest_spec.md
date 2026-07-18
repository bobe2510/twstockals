# Playbook 階段1回測規格（預先鎖定）

對照腳本：`src_scripts/research/run_playbook_revision_backtest.py`  
報告：`reports/latest/playbook_revision_backtest.md`

## 組別

| ID | 說明 |
|----|------|
| A_baseline | 評等 B+ 進；破年線 **或**（獲利且破 10MA）全出 |
| B_year_only | B+ 進（Level1＋年線上）；僅破年線袖口（半倉→再清） |
| C_year_cap | 同 B；進場火力 12%；市值＞12% 再平衡 |
| BH | 00631L 長抱參考 |

## 通過標準

見腳本 `PASS_RULES`／`judge_gate()`：

- PASS_SAFE / PASS_CP / PASS_NEUTRAL → 可建議階段2  
- FAIL → 停實作，另開評估計畫  

**門檻修訂（2026-07-18）：** `PASS_CP` 的 MDD 惡化容許由 1pt **放寬至 3pt**（使用者明確同意後重判）。
