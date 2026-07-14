# 🛠️ 活躍執行腳本說明與維運指南

本目錄存放專案的所有活躍 Python 執行腳本。策略已轉向：**持倉監控＋見機停損停利**，主力倉以 **CP（高報酬 × 低上班操作）** 選優。

---

## 📋 活躍腳本清單與使用說明

### 1. 🚀 一鍵聯動主核心：`market_screener.py`
*   **功能**：下載全市場快取、產出選股溫度計報告，並聯動持股診斷。
*   **定位變更**：排行榜當作**環境溫度計**，**不當新開個股倉的下單清單**。
*   **執行指令**：
    ```bash
    python src_scripts/market_screener.py
    ```

---

### 2. 📊 個人持倉處置診斷：`analyze_portfolio_deep.py`
*   **功能**：讀取 `config/my_targets.json`，產出停損／停利、錯誤策略出清、多資產配置差距、`levels.json`，並嵌入 CP 結論。
*   **執行指令**：
    ```bash
    python src_scripts/analyze_portfolio_deep.py
    ```

---

### 3. 🚨 盤中緊急防禦：`scan_black_swan.py`
*   **功能**：盤中僅處理**緊急**事件（大盤／持股急跌、停損觸價、匯率、多資產劇震），並 Telegram+Email 推播。
*   **參數**：
    *   `--force`：略過時段限制
    *   `--no-popup`：不彈 Windows 視窗（排程建議）
    *   `--asset-window`：晚間多資產視窗（20:00~05:00）
*   **執行指令**：
    ```bash
    python src_scripts/scan_black_swan.py --force --no-popup
    python src_scripts/scan_black_swan.py --force --asset-window --no-popup
    ```

---

### 4. 📋 收盤後執行清單：`scan_position_levels.py`
*   **功能**：讀取 `reports/latest/levels.json`，確認停損／停利／建倉／年線狀態，產出 `eod_action_list.md` 並推播一則摘要（建議 14:10 排程）。
*   **執行指令**：
    ```bash
    python src_scripts/scan_position_levels.py --force
    ```

---

### 5. 🏅 CP 回測選優：`run_etf_backtest.py`
*   **功能**：比較 0050／正2／年線／季線／混合策略，計算
    `CP = CAGR - 0.25*|MDD| - 1.5*WorkdayOpsPerYear`，輸出：
    *   `reports/latest/etf_backtest_report.md`
    *   `reports/latest/strategy_cp_ranking.md`
    *   `reports/latest/strategy_cp_best.json`
*   **執行指令**：
    ```bash
    python src_scripts/run_etf_backtest.py
    ```

---

## 6. 📣 通知模組：`notify.py` + 雲端排程
*   Telegram + Email；支援 `config/api_keys.json` 或環境變數（GitHub Secrets）。
*   統一入口：`python src_scripts/run_all_alerts.py --mode all|intraday|eod|multi --force`
*   **免費雲端**：GitHub Actions（見 [`docs/CLOUD_ALERTS.md`](../docs/CLOUD_ALERTS.md)），不必自架 Heroku／家用主機常開。
*   多資產：`scan_multi_asset.py`（黃金評等金額、匯率、BTC、VOO/QQQ 觀測）
*   測試：
    ```bash
    python src_scripts/notify.py
    python src_scripts/run_all_alerts.py --mode multi --force --force-notify
    ```

---

### 📥 7. 個股手動更新：`fetch_stock_data.py`
```bash
python src_scripts/fetch_stock_data.py 2330
```

---

## ⚙️ 設定檔

| 檔案 | 用途 |
|------|------|
| `config/my_targets.json` | 持股、觀測、`multi_asset`、`allocation_targets`、`force_exit_codes` |
| `config/alert_rules.json` | 觸價規則、閾值、冷卻時間 |
| `config/api_keys.json` | FinMind／Gemini／Telegram／SMTP（勿提交公開） |

### 補數量範例（黃金／外匯／加密）
在 `my_targets.json` 的 `multi_asset` 填入：
```json
"gold_passbook": { "unit": "g", "qty": 10, "cost_per_g": 2500 },
"forex_usd": { "qty": 1000, "cost_twd": 31000 },
"crypto": [{ "symbol": "BTC-USD", "qty": 0.01, "cost_usd": 600 }]
```

---

## 🗓️ 建議排程

| 時間 | 指令 |
|------|------|
| 盤中每小時 | `scan_black_swan.py --no-popup` |
| 約 14:10 | `scan_position_levels.py`（主推播） |
| 晚間 | `scan_black_swan.py --asset-window --no-popup` |
| 盤後／週末 | `market_screener.py` 或 `analyze_portfolio_deep.py`；必要時 `run_etf_backtest.py` |

---

## 📁 歷史備份

最新報告在 `reports/latest/`，歷史副本在 `reports/history/`。
