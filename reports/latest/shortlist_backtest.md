# 短名單回測（策略目錄 §5.1）

- 產生時間：2026-07-18 04:19
- 起始資金：1,000,000（黃金分批投入上限 300,000）
- CP：`CAGR − 0.25|MDD| − 1.5×年化操作`；OOS ≈ 近 504 根（~2y）
- 執行：`python src_scripts/run_shortlist_backtest.py`

## 結果總表

| id | 說明 | CAGR% | MDD% | CP | 買入次 | 終值(萬) | 勝B&H | OOS CAGR\|MDD\|CP |
|----|------|------:|-----:|---:|------:|--------:|:-----:|-------------------|
| `1_gold_baseline_B+` | GOLD baseline B+ | +4.3 | -17.5 | -3.1 | 26 | 123.3 | N | +3.89|-17.48|-2.73 |
| `1_gold_hier_200_B+` | GOLD 200DMA∩B+ | +3.2 | -17.5 | -3.5 | 20 | 117.2 | N | +3.89|-17.48|-2.73 |
| `1_VOO_baseline_B+` | VOO baseline B+ | -1.5 | -39.6 | -45.0 | 279 | 92.9 | N | +6.6|-23.08|-25.86 |
| `1_VOO_hier_200_B+` | VOO 200DMA∩B+ | -0.6 | -27.4 | -22.2 | 123 | 97.2 | N | +1.94|-16.44|-17.77 |
| `2_VOO_abs_mom_12m` | VOO abs mom 12m | +10.2 | -19.6 | +4.8 | 5 | 162.2 | N | +13.45|-19.57|8.26 |
| `1_VXUS_baseline_B+` | VXUS baseline B+ | -8.5 | -53.1 | -61.8 | 333 | 64.4 | N | +7.41|-17.76|-23.43 |
| `1_VXUS_hier_200_B+` | VXUS 200DMA∩B+ | -0.2 | -18.6 | -21.3 | 137 | 99.0 | N | +2.99|-14.63|-17.47 |
| `2_VXUS_abs_mom_12m` | VXUS abs mom 12m | +4.3 | -21.8 | -1.9 | 7 | 123.6 | N | +10.84|-14.67|6.87 |
| `1_QQQ_baseline_B+` | QQQ baseline B+ | +7.6 | -41.0 | -19.7 | 142 | 144.1 | N | +20.64|-13.43|4.69 |
| `1_QQQ_hier_200_B+` | QQQ 200DMA∩B+ | +7.9 | -13.4 | -3.1 | 64 | 146.0 | N | +2.15|-13.43|-12.01 |
| `2_QQQ_abs_mom_12m` | QQQ abs mom 12m | +11.7 | -25.7 | +4.4 | 8 | 173.7 | N | +16.28|-23.92|10.0 |
| `2_dual_mom_VOO_VXUS` | Dual mom VOO↔VXUS | +6.8 | -19.7 | -2.6 | 38 | 139.0 | N | +6.88|-19.74|-6.45 |
| `3_gold_baseline_B+` | GOLD baseline B+ (hurst ctrl) | +4.3 | -17.5 | -3.1 | 26 | 123.3 | N | +3.89|-17.48|-2.73 |
| `3_gold_hurst_regime` | GOLD Hurst regime | +1.0 | -17.5 | -6.3 | 25 | 105.1 | N | +3.37|-17.48|-3.55 |
| `4_usd_sell_fixed_1p5` | USD sell fixed +1.5% | +0.9 | -11.5 | -2.6 | 6 | 105.0 | N | -0.35|-11.53|-4.13 |
| `4_usd_sell_sigma` | USD sell μ+1σ (floor 1.5) | +0.9 | -11.5 | -2.6 | 6 | 105.0 | N | -0.35|-11.53|-4.13 |
| `4_usd_sell_p75` | USD sell P75 bias (floor 1.5) | +1.5 | -11.5 | -2.0 | 5 | 107.8 | N | -1.21|-11.53|-4.84 |
| `4_usd_sell_sleeve` | USD sleeve 50%@1.5 / 100%@3.0 | +1.7 | -2.7 | -0.8 | 4 | 109.1 | N | +1.1|-2.17|-1.84 |
| `5_gold_allin_B+` | GOLD all-in B+ | +4.3 | -17.5 | -3.1 | 26 | 123.3 | N | +3.89|-17.48|-2.73 |
| `5_gold_longMA_allin_B+` | GOLD longMA filter all-in B+ | +3.2 | -10.9 | -2.6 | 25 | 116.8 | N | +6.74|-10.87|1.62 |
| `5_gold_tranche_B+` | GOLD tranche B+ live map | +0.4 | -5.0 | -5.6 | 53 | 102.0 | N | -0.94|-5.04|-5.2 |
| `5_gold_longMA_tranche_B+` | GOLD longMA + tranche B+ | +0.1 | -3.2 | -4.6 | 39 | 100.4 | N | -0.24|-3.2|-4.19 |

## 分組冠軍（全樣本 CP）

- **1 階層濾網**：`1_QQQ_hier_200_B+` — CP -3.1｜CAGR +7.9%｜MDD -13.4%｜QQQ 200DMA∩B+
- **2 動量**：`2_VOO_abs_mom_12m` — CP +4.8｜CAGR +10.2%｜MDD -19.6%｜VOO abs mom 12m
- **3 Hurst**：`3_gold_baseline_B+` — CP -3.1｜CAGR +4.3%｜MDD -17.5%｜GOLD baseline B+ (hurst ctrl)
- **4 美金賣出**：`4_usd_sell_sleeve` — CP -0.8｜CAGR +1.7%｜MDD -2.7%｜USD sleeve 50%@1.5 / 100%@3.0
- **5 黃金長均**：`5_gold_longMA_allin_B+` — CP -2.6｜CAGR +3.2%｜MDD -10.9%｜GOLD longMA filter all-in B+

## 解讀注意

- 未寫入 live policy；僅研究對照。
- VOO／VXUS 純 B+ 全日倉買入 100+ 次：拉回評等常在 ma50 下仍給 B+，與「破 ma50 全出」衝突 → **churn 失真**；階層／動量才有參考價值。
- Hurst 為簡化估計，對窗長敏感；本輪輸 baseline → 擱置。
- 美金袖口 MDD 從 -11.5% → -2.7%，與現行 live 減碼方向一致。
- Dual Momentum 的 B&H 對照為同期 VOO；單資產絕對動量 CP 更好。
- **可續作：** 絕對動量 6／10／12m 穩健性；其餘暫不上 policy。

