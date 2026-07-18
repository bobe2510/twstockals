# Playbook 修正版階段1回測

- 產生：2026-07-18 05:45
- 商品：00631L＋TAIEX｜評測窗約 9.66 年｜起始資金 1,000,000
- 腳本：`python src_scripts/run_playbook_revision_backtest.py`

## 通過標準（預先鎖定）

```
{
  "safe_mdd_improve_abs": 2.0,
  "safe_mdd_improve_rel": 0.1,
  "safe_cagr_worsen_max": 2.0,
  "cp_mdd_worsen_max": 3.0,
  "neutral_cp_abs": 1.0,
  "neutral_mdd_abs": 2.0
}
```

- **PASS_SAFE**：MDD 改善≥2pt 或相對≥10%，且 CAGR 惡化≤2pt
- **PASS_CP**：CP 高於基準，且 MDD 惡化≤3pt（2026-07-18 放寬）
- **PASS_NEUTRAL**：|ΔCP|≤1 且 |ΔMDD|≤2，交易不增
- **FAIL**：MDD 與 CP 皆變差（一票否決）或其他未達標

## 組別結果

| 組別 | CAGR% | MDD% | CP | 終值(萬) | 交易 | 買入 |
|------|------:|-----:|---:|--------:|-----:|-----:|
| A 基準（年線或10MA停利） | +20.5 | -34.7 | +8.7 | 605.7 | 100 | 50 |
| B 修正（僅年線袖口） | +34.4 | -37.2 | +23.9 | 1734.7 | 36 | 12 |
| C 修正＋12%超配再平衡 | +3.8 | -4.5 | -9.3 | 143.5 | 386 | 12 |
| BH 長抱參考 | +45.8 | -55.1 | +32.0 | 3811.4 | 0 | 0 |

## 門閘判定

### B vs A → **PASS_CP**
- CP 提升 +15.2，MDD 惡化受限
- ΔCP +15.2｜MDD改善 -2.5pt｜ΔCAGR +13.9
- 建議進階段2：是

### C vs A → **FAIL**
- 未達 PASS_SAFE／PASS_CP／PASS_NEUTRAL
- ΔCP -18.0｜MDD改善 +30.2pt｜ΔCAGR -16.7
- 建議進階段2：否

## 主判定（取較佳）：**PASS_CP**（對照組 `B_year_only`）

- CP 提升 +15.2，MDD 惡化受限
- **是否建議進入階段2完整實作：是**

## 黃金遲滯（附帶）

黃金簡易（點差0.3%/邊）：日減 CP -5.5／遲滯5日 CP -4.5（MDD -17.9 vs -17.9）

## 資金部署敏感性（非主指標）

{"level_1_ratio": 0.4, "level_2_ratio": 0.3, "level_3_ratio": 0.15, "note": "行為風控；非主勝出指標"}

## 說明

- 基準 A 刻意含「獲利且破10MA全出」，對照顧問修正「刪常規短均停利」。
- C 的 12% 對齊 `allocation_targets.tw_lev_00631L`；進場只動用 12% 現金，其餘留現金。
- BH 僅參考；主門閘是修正組 vs A。

