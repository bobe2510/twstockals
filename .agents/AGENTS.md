# Taiwan Stock & Warrant Analysis Guidelines

This document defines the core strategies, filters, and behavioral rules for analyzing Taiwan stocks and warrants. Future AI agents collaborating in this workspace must adhere to these guidelines.

---

## 1. Core Stock Selection Strategy (70% Chips / 30% Technicals)

Taiwan's stock market is highly driven by capital flow and institutional chips. Thus, all stock analyses must weigh chip flow significantly higher than technical patterns.

### A. Chip Analysis (Weight: 70%)
*   **Proportional Volume Scaling (吃貨比例化)**: Do not use absolute transaction lot thresholds (e.g. `>500` or `>2000` lots) for scoring. Calculate `inst_ratio` = 5-day Net Institutional Buy (Foreign + Trust) / 20-day Average Daily Volume.
    *   `inst_ratio >= 15%`: Strong Accumulation (`5日法人大買超` $\rightarrow$ +25 Profit points / +15 Portfolio points)
    *   `inst_ratio >= 5%`: Steady Accumulation (`5日法人買超` $\rightarrow$ +15 Profit points / +10 Portfolio points)
    *   `inst_ratio > 0%`: Mild Accumulation ($\rightarrow$ +5 Profit/Portfolio points)
*   **Institutional Buying Streak (15%)**: Track consecutive buying days by institutions. A streak of $\ge 3$ days indicates systematic accumulation.
*   **Smart Margin Leverage Classification (融資特性分流)**: Distinctly separate retail margin from major player margin:
    *   **Major Player Leverage (主力資增建倉鎖碼)**: If margin increases while Price > 20MA, Institutions are net buying, and Margin Usage (`Balance / Limit`) is $< 25\%$. Do **not** penalize as risk; classify as `🔥 主力資增建倉鎖碼` ($\rightarrow$ +5 Profit/Portfolio points).
    *   **Retail Overheating (散戶過熱)**: If margin increases but fails the above conditions. Classify as `🔴 融資飆升` ($\rightarrow$ +15 Risk points, no bonus).
    *   **Retail Exit (資減價平/價揚)**: Margin decreases (`margin_diff_5d < 0` $\rightarrow$ +5 Profit/Portfolio points; `<-500` lots $\rightarrow$ +10 points) which signifies retail capitulation.

### B. Technical Analysis (Weight: 30%)
*   **Moving Average (MA) Alignment (15%)**: Check if the price is in a bullish alignment (Price > 5MA > 10MA > 20MA).
*   **Momentum Indicators (10%)**: Use 9-day KD. Look for low-level golden crosses or strong bullish divergences.
*   **20MA Bias (5%)**: Check the distance of the price from the 20MA (月線乖離率).
    *   **$\le 4.0\%$**: Safe entry point (🟢 安全低乖離 $\rightarrow$ -10 Risk points).
    *   **$> 15.0\%$**: Overextended (🔴 月線高乖離 $\rightarrow$ +30 Risk points).
    *   **$> 25.0\%$**: Severely overextended (🔴 月線超高乖離 $\rightarrow$ +45 Risk points).

### C. Sniper Priority Score (狙擊手實戰權重評分)
To dynamically rank the priority of adding positions or entry, a unified **Sniper Priority Score** is calculated and used to sort the holdings and watchlists:
$$\text{Sniper Score} = (\text{p\_score} - \text{r\_score}) + \text{InstBonus} + \text{StreakBonus} + \text{BiasBonus} + \text{WashoutFilter}$$
*   **Base Score**: `p_score - r_score` from the multi-factor model.
*   **InstBonus (吃貨比加分)**:
    *   `inst_ratio >= 15%`: $+15$ points
    *   `inst_ratio >= 50%`: $+35$ points (adds $+20$ on top of the $+15$)
*   **StreakBonus (連買天數加分)**: $\min(\text{consecutive\_buy}, 5) \times 2$ (up to $+10$ points).
*   **BiasBonus (月線乖離獎懲)**:
    *   `bias_20 <= 5.0%`: $+25$ points (Safe low bias zone)
    *   `bias_20 >= 8.0%`: $-15$ points (High bias warning)
    *   `bias_20 >= 12.0%`: $-40$ points (Severe bias warning)
*   **WashoutFilter (洗盤過濾器)**: If a stock has a KD death cross but is highly consolidated with `inst_ratio >= 100.0%` and `bias_20 <= 5.0%`, it gets a $+15$ points bonus to compensate for the KD penalty, representing a prime buy-on-dip opportunity.

---

## 2. Foreign vs. Local Capital Classification (外資與內資主導分類)

Classify and flag stocks based on **Foreign Ownership Ratio (外資持股比)** to align with different market drivers and risk profiles:

*   **🚨 Foreign Capital Dominated (外資主導 $\ge 40\%$)**: 
    *   *Examples*: 6415 (Siligy), 6451 (Xinxin), 5243 (Eson), 2383 (TUC), 2303 (UMC).
    *   *Characteristics*: Highly vulnerable to foreign capital outflows during global macro sell-offs or TWD depreciation.
    *   *Rule*: Never chase highs. Sell immediately if the price breaks the 20MA on high volume with foreign net selling.
*   **✅ Local Capital Dominated (內資主導 $\le 15\%$)**:
    *   *Examples*: 4764 (Double Bond), 6693 (廣閎科), 3693 (Allied), 3706 (MiTAC), 3455 (Utechzone).
    *   *Advantage*: Driven by local investment trusts, groups, or main forces. Highly stable and resilient against foreign capital outflows.

---

## 3. Macro Multi-Filters & Safe Purchase Zones (大盤多空濾網與買點)

*   **TAIEX Multi-Filter (大盤多空濾網 - 三階防禦與前置減碼機制)**:
    *   Calculate TAIEX (Taiwan Weighted Index) Close vs. its 20MA.
    *   **Level 1: Bullish Zone (多頭安全區)** (`TAIEX > 20MA` 且 乖離率 $> 1.5\%$): 市場環境健康，可積極布局強勢動能與低風險標的。
    *   **Level 2: Pre-emptive Warning Zone (前置減碼警戒區)** (`TAIEX > 20MA` 但 乖離率 $\le 1.5\%$): 大盤極度逼近月線，面臨破位風險。**採取前置減碼對策**：暫停積極開倉與追高；緊縮持有個股之停損至 10MA 或 5 日低點；預防性回收時間毒藥（如反1）及槓桿型/弱勢標的資金。
    *   **Level 3: Bearish Zone (空頭避險區)** (`TAIEX < 20MA`): 系統性風險高。啟動防風機制，降低整體持股成數至 $40\%$ 以下，全面暫停波段/突破策略，避開外資主導股。
*   **Portfolio & Watchlist Buy Levels (持股與觀測進場加碼點位)**:
    *   **First Entry Point (初次進場點 - 觀測股)**: For stocks *not yet held*, focus on pullbacks to the 5MA or 10MA to test support.
    *   **Major Player Entry Point (主力加碼與月線防守點 - 實體持股/已建倉)**: For stocks *already held*, focus on:
        *   **10MA (主力加碼點)**: Pullbacks to the 10MA to add/accumulate for bullish stocks.
        *   **20MA (月線支撐點)**: Pullbacks to the 20MA (月線) to protect or do final accumulation.
        *   **Capital Preservation Warning (減碼不加碼原則)**: If the holding stock is an ETF and has a strategy suggesting "出清" (exit) or "減碼" (reduce) (e.g., leveraged reverse ETFs or weak regional ETFs), do **NOT** suggest any add-on levels (mark as `⚠️ 建議減碼/不加碼`), to prevent averaging down on depreciating assets.

---

## 4. Black Swan Real-Time Monitoring & Exchange Alerts (黑天鵝防衛網)

*   **New Taiwan Dollar (TWD) Depreciation Alert**:
    *   Monitor Yahoo Finance `USDTWD=X` daily exchange rate.
    *   If TWD depreciates by **$\ge 0.4\%$** in a single day, trigger a warning in the report and desktop alert, indicating high risk of foreign capital flight.
*   **Scan Window Restriction (盤中執行時間限制)**:
    *   Black-swan scans may run in session, but **must not push individual-stock stop / support-break alerts intraday** (avoid selling into the dumb valley / 阿呆谷).
    *   Stock defense breaks are confirmed around **13:10** (`--close-confirm`), re-checked vs **13:30** close; execute after **13:40** or next open. Freeze **09:00–09:30**.
    *   Macro / FX / inverse-ETF (`00632R` force-exit) alerts may still notify intraday.
    *   Runs outside the intended mode/window must exit quickly unless forced.
*   **Hidden Execution Wrapper (VBScript)**:
    *   Deploy standard background tasks with a VBScript wrapper to suppress CMD windows (`WshShell.Run "python ...", 0, False`), allowing non-disruptive background checks in the user context.

---

## 5. Engineering & Automation Guidelines for AI Agents

To maintain stability, reliability, and correctness in this workspace's automation scripts and reports, collaborating AI agents must adhere to these engineering rules:

### A. Path Encoding & Windows Compatibility (Chinese Folder Paths)
*   **The Issue**: The workspace is located inside a Google Drive directory containing Traditional Chinese characters (`我的雲端硬碟`). Hardcoding absolute paths with Chinese characters inside system scripts (such as VBScript or PowerShell) causes CP950/ANSI encoding mismatches in the Windows environment, leading to "script file not found" errors.
*   **The Rule**: Never hardcode Chinese path names in system scripts.
    *   *PowerShell*: Use `$PSScriptRoot` (e.g., `$vbsPath = Join-Path $PSScriptRoot "run_scan.vbs"`) to dynamically resolve paths in Unicode.
    *   *VBScript*: Dynamic parent folder resolution must be used to locate peer files:
        ```vbscript
        Set objFSO = CreateObject("Scripting.FileSystemObject")
        strPath = objFSO.GetParentFolderName(WScript.ScriptFullName)
        WshShell.Run "python """ & strPath & "\scan_black_swan.py""", 0, False
        ```

### B. Dynamic Report Parameterization
*   **The Rule**: Do NOT hardcode date headers, date ranges, or calculated variables (such as portfolio ROI, current prices, or monthly bias) in the report generation code or dictionaries.
*   **Implementation**:
    *   Search the `data/` directory dynamically to find the latest folder (e.g., `sorted(dirs)[-1]`).
    *   Extract the latest trading date and 5-day range from the K-line CSV files.
    *   Format strategy descriptions dynamically (using Python string formatting, e.g., `{roi:+.2f}%`, `{bias_20:+.1f}%`) to avoid stale text data.

### C. Share Volume to Lot Scaling (TWSE / FinMind API Units)
*   **The Issue**: The TWSE/FinMind API returns institutional transaction volumes in shares (股), not in lots (張). 
*   **The Rule**: For all tables, reports, and quantitative scoring models, scale institutional volume by dividing by `1000` to convert to lots (張). This aligns with standard Taiwan stock market terminology and prevents scoring glitches (e.g., small trades triggering massive scoring spikes).

### D. Data Completeness & Fetch Scheduling
*   **The Issue**: In Taiwan's stock market, daily closing prices are finalized at 1:30 PM, but institutional and margin flows are not complete on the API until 3:00 PM - 5:00 PM.
*   **The Rule**: Any script fetching the current day's complete closing and chip data must only be scheduled after 5:00 PM local time. If run before that, the script must automatically locate and use the previous trading day's folder as the latest complete dataset.

### E. Non-Blocking Headless Execution (MessageBox Warning)
*   **The Issue**: Calling GUI dialog windows (like `ctypes.windll.user32.MessageBoxW`) inside background/headless terminal runs (such as IDE command runs or scheduled tasks running in hidden sessions) will block the script indefinitely since the dialog box is invisible and cannot be closed by a user.
*   **The Rule**: Ensure background execution tasks do not call blocking GUI code unless explicitly run within the user's active desktop session. Logs should be written first, and GUI alerts should be triggered in a non-blocking/isolated process (e.g., run via Windows Task Scheduler in the logged-in user context).

---

## 6. Unified Project Structure & Workflow (專案目錄結構與聯動工作流規範)

### A. Directory Map (目錄配置原則)
*   **`src_scripts/`**: 活躍腳本（雲端推播鏈）。根目錄禁止放裸腳本。
*   **`src_scripts/research/`**: 回測／校準腳本（少跑，不進排程；產出在 `reports/latest/backtest/`）。
*   **`config/`**:
    *   `config/my_targets.json`: **唯一手改真相**（portfolio／cleared／multi_asset／cash；`deployable_cash_twd` 為可投入現金唯一欄位）。
    *   `config/alert_rules.json`、`config/grade_buy_policy.json`
*   **`reports/latest/`**: 執行產物 — 優先看 `CURRENT_STATE.md`、`eod_action_list.md`、`levels.json`、`exit_watch_1310.md`
*   **`reports/history/`**: 時間戳備份（sync 自動保留 30 天）
*   **`deploy/droplet/`**: 雲端主節點（DigitalOcean systemd timers）；GitHub Actions 已停用移除
*   2026-07 精簡：`src_scripts/legacy/`、`reports/archive/`、`config/archive/` 已移除，需要時從 git 歷史找回。

### B. Execution Workflow (日常聯動)
*   **雲端／本機統一入口**: `python src_scripts/run_all_alerts.py --mode …`
    *   `close_confirm`／`eod` 會先跑 `sync_runtime_state` + `refresh_levels_live`
*   **對齊狀態**: `python src_scripts/sync_runtime_state.py`
*   **出清倉監控**（持續）: `scan_exit_watch`（13:10 close_confirm）+ `scan_position_levels`（13:45 digest_close 內）讀 `my_targets` 的 `gradual_exit`／個股殘倉
*   **手動補價**: `python src_scripts/fetch_stock_data.py <symbol>`
*   **黑天鵝**: `python src_scripts/scan_black_swan.py`（或經 run_all_alerts）

### C. Report Rules
*   勿手改 `holdings.json`／`levels.json`／`CURRENT_STATE.md`
*   勿依過期 `portfolio_and_watchlist` 或任何舊報告下單

---

## 7. Smart Execution & Market Timing Rules (聰明交易與執行規範)

To avoid non-essential drawdowns during high-volatility regimes and prevent panic selling at the opening bell, follow these execution principles:

*   **A. Time-Window Execution Restriction (交易執行時間窗口)**:
    *   **Freeze Open Panic (開盤冷靜期)**: Do **NOT** execute any panic stop-losses or reductions during the opening session (**`09:00 ~ 09:30`**). This is when retail panic and broker margin liquidations peak, often creating the absolute low of the day.
    *   **Rebound Execution Wave (反彈減碼窗口)**: Target the **`10:00 ~ 11:30`** window to execute reductions. This is when institutional/government support typically flows in, lifting the index for a technical rebound.
*   **B. Closing-Basis Support Confirmation (收盤判定與兩日不站回原則)**:
    *   All support breaks (such as 20MA or 5-day low) must be verified at the **`13:30` closing price** rather than temporary intraday dips (to filter out fake breakouts).
    *   For **Local Capital Dominated** stocks with solid chip accumulation, allow a **2-day grace period** (兩日不站回法則) before executing stops.
*   **C. Smart Additions / Dip-Buying (洗盤低接增資)**:
    *   If a stock is **Local Capital Dominated ($\le 15\%$ foreign ownership)**, has a high institutional chip score (`inst_ratio >= 50%` or consecutive buy streak $\ge 3$ days), and pulls back close to its 20MA ($\le 4\%$), treat the pullback as a **Smart Addition (增資)** zone rather than a stop-loss trigger.
*   **D. Time Poison Cash Liquidation (時間毒藥變現法)**:
    *   Leverage index drops to sell Inverse ETFs (like `00632R`) at high points to reclaim cash, and never buy-and-hold reverse products for long-term.

---

## 8. Holdings-First Strategy & CP Selection (持倉監控優先與 CP 選優)

### A. Strategy Shift (策略轉向)
*   **Default**: Do **not** open new single-stock positions. Screener／社群選股腳本已移除（2026-07 精簡），不當下單來源。
*   Allowed actions only: EOD entry confirmation, add-on at 10MA (non `force_exit`), trailing take-profit, hard stop at 5-day low, and priority liquidation of error strategies / `gradual_exit`（如 00687B）.
*   Individual stocks are **residual / exit-only** satellites; do not expand the stock pool.

### B. CP Ranking Rule (最高報酬 × 最少上班操作)
\[
\text{CP} = \text{CAGR} - 0.25\cdot|\text{MDD}| - 1.5\cdot\text{WorkdayOpsPerYear}
\]
*   EOD trades (close signal → next open) count **0.2** workday-ops each.
*   Intraday-mandatory trades count **1.0** each.
*   Prefer the **highest CP** strategy as the core sleeve (typically 00631L × 200MA EOD or 0050+正2 hybrid). Never promote high-turnover chip day-trading as core.

### C. Workday Ops Window
*   Avoid discretionary trading during **09:00–17:00** weekdays when possible.
*   Primary execution window: **after 13:40** or next-day open; US/IB orders in the evening.
*   Intraday push (`scan_black_swan.py`): **emergency only**. Routine entry/TP → `scan_position_levels.py` EOD digest.

### D. Multi-Asset Config
*   `config/my_targets.json` supports `multi_asset` (gold passbook, USD forex, crypto, us_etf), `allocation_targets`, and `force_exit_codes`.
*   Quantities may be `null` until filled; reports show 待填／待補倉.
*   Notifications: `config/api_keys.json` fields `TELEGRAM_*`, `SMTP_*`, `NOTIFY_DRY_RUN`. Use `src_scripts/notify.py`.

### E. Key Artifacts
*   `config/my_targets.json` — **source of truth**
*   `reports/latest/CURRENT_STATE.md` — synced digest（決策優先）
*   `reports/latest/levels.json` / `holdings.json` — generated; `sync_runtime_state` + `refresh_levels_live`
*   `reports/latest/eod_action_list.md` / `exit_watch_1310.md` — EOD／出清倉
*   `reports/latest/backtest/strategy_cp_ranking.md` + `strategy_cp_best.json` — CP（少跑回測產出）


