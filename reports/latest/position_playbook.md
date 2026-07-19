# 持倉操作 Playbook（四件套）

- 產生：2026-07-19 16:02
- 目標函數：風險調整後可執行長期財富（CP 哲學），非無約束最大終值。階段1 PASS_CP（MDD容許3pt）後實作。
- 階段1：PASS_CP — B 僅年線袖口 vs A：ΔCP+15.2，MDD惡化2.5pt≤3pt。C 現金版不採為進場預設。
- NAV 粗估：總計約 8,355,510｜已投資 2,495,727｜現金 5,859,783｜可再投入 1,859,783｜Level **3**
- Intent：`reports/latest/action_intents.json`

## 資金部署

- 今日建議：**下調至 878,967 元**（推播≠已改 `deployable_cash_twd`）

## 各商品四件套

| 代號 | 角色 | 建倉 | 加倉 | 停利／再平衡 | 停損 | 持倉%/目標% | 今日 |
|------|------|------|------|--------------|------|-------------|------|
| 00631L | core_tw_lev | conditional：≥B＋L1＋年線上 | conditional：評等＋止穩；L≥3／破年線禁止 | 僅超配再平衡（無常規10MA停利） | 破年線袖口減約1/3 | 3.5/12.0 | gate：禁止加倉（Level≥3）｜續抱年線 |
| 0050 | core_tw | ≥B 分批（flat） | 評等升級不加碼；新錢依 watch_grades | 無（純長抱 B方案）；僅超配再平衡 | 無（exit_rule_backtest 2026-07-18） | 0.0/35.0 | 尚未建倉（新錢走 watch_grades） |
| 00687B | gradual_exit | structural 關（目標權重0） | structural 關｜解禁＝改 allocation＋role | 逢彈賣約1/3至清完 | 不砍阿呆谷 | 1.3/0.0 | 逢彈可賣 1000 股（約持倉 33%）→轉現金／美金／黃金 |
| 2301 | stock_residual | structural 關（不擴股池） | structural 關 | ROI12/25%＋移動均線（僅獲利） | 5日低兩日不站回→出清 | — | 持有 1000 股｜禁止加倉｜詳 EOD levels |
| 3484 | stock_residual | structural 關（不擴股池） | structural 關 | ROI12/25%＋移動均線（僅獲利） | 5日低兩日不站回→出清 | — | 持有 5000 股｜禁止加倉｜詳 EOD levels |
| GOLD | gold | ≥B；budget 見 policy | ≥B＋未滿budget（買滿長抱） | 僅超配再平衡；50MA停利已停用 | 未過gate＝不加（非硬停損） | 5.9/25.0 | 持有約 492,088 元 |
| USDTWD | usd_fx | ≥A | ≥A；乖離≥1.5%關加 | 1.5%/3%袖口減碼 | 同均值回歸減碼 | 6.2/gold_fx合計 | 持有約 520,489 元 |
| CRYPTO | crypto | 超配則先 trim；達標後才談建倉 | 達標前禁止 | 主＝再平衡至目標占比 | 破50MA優先清超額 | 7.8/3.0 | 超配｜建議減約 399,335 元市值至≤3% |

## 今日 Intent（已去重優先序）

1. [gate_blocked] 00631L hold — ｜Level≥3 禁止加倉；破年線才減碼
2. [rebalance_trim] CRYPTO sell — 約 399,335 元｜加密超配：主路徑再平衡減碼（非只等破線）
3. [lower_deploy_budget] CASH adjust — 約 878,967 元｜建議可再投入上限 1,859,783→878,967元（地板2,929,892）；確認後再改設定

## 規則備註

- 正2：**無常規10MA停利**（階段1 B／PASS_CP）；破年線才袖口減。
- 超配：主路徑再平衡；gate 關閉時報告說明、不催買。
- 數量：台股整張；不足1張標餘額出清。

