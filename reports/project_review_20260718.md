# 專案健檢報告（2026-07-18）

審查範圍：`.github/workflows/`、`src_scripts/` 核心推播鏈（run_all_alerts / notify / event_bus / eval_market_events / scan_black_swan / sync_runtime_state / market_data / ingest_common / check_ingest_health / build_daily_digest）、`config/`、`.agents/` 文件、`reports/` 狀態一致性。

整體架構（event_digest 模型、edge 事件去重、cleared_positions 多層防呆、密鑰 gitignore、時區統一 tw_time）設計良好。以下為發現的不合理處，依風險排序。

---

## A. 高風險（建議優先修）

### A1. GitHub Actions 免費額度可能被 crypto ingest 吃光 → 排程全停
`ingest.yml` 的 crypto cron `0,15,30,45 * * * *` 全年無休每 15 分鐘跑一次（≈96 次/日），每次都 checkout + `pip install -r requirements.txt`（約 2–3 分鐘）。私有 repo 免費額度 2,000 分鐘/月，光這條就可能用掉 5,000+ 分鐘/月；**超額後包含 13:10 close_confirm 停損確認在內的所有排程都會停擺**。
建議（擇一或並用）：
- crypto 降頻至 30–60 分鐘，或只在需要的時段（如台北 11:00–13:00、19:00 前後）跑
- workflow 加 `actions/cache` 快取 pip，或精簡 crypto job 的相依安裝
- 把 crypto ingest 移到 droplet cron（文件本來就規劃 droplet 為主節點）

另注意：GitHub 對 60 天沒有 commit 活動的 repo 會**自動停用 scheduled workflows**，需留意收信重新啟用。

### A2. `sync_runtime_state.py` 硬編碼已出清代號（違反自家 AGENTS.md 5B 規則）
`CLEARED_HINT = re.compile(r"(00632R|00882|3483|5469|6191|…)")`，且 `stamp_stale_portfolio_report`／`stamp_eod_list` 內又硬列同一組代號、`write_current_state` 硬編碼「個股殘倉（2301／3484）」「美債 00687B」等文案。
→ 未來出清 2301/3484 或新增出清標的時，scrub 不會生效、CURRENT_STATE 文案會過期誤導。
建議：從 `my_targets.cleared_positions`／`portfolio` 動態組 regex 與文案。

### A3. 13:15 備援 close_confirm 的去重機制有 race，幾乎必重複執行
備援去重靠 `close_confirm_ran.json`（Actions cache 還原）。13:10 主跑通常要 3–5 分鐘才結束並存 cache；13:15 備援啟動時 restore 到的是**更早的 cache**，看不到今日 marker → 備援每天都會完整重跑一次（事件層有 edge 去重所以推播不至於重複，但白耗一倍分鐘數、也增加 API 負擔）。
建議：備援 cron 改 13:25–13:30。

### A4. 無台股假日行事曆
`build_daily_digest.is_tw_trading_day()` 只判斷平日。國定假日（春節、颱風假等）仍會：跑 close_confirm/digest_close、推「收盤執行報」；且連假超過 48h 時 `check_ingest_health` 的 tw_eod stale 檢查會**誤報 ingest 異常**。
建議：以「warehouse 今日是否有 TAIEX 新 bar」判定交易日，或內建 TWSE 年度行事曆 JSON。

---

## B. 中風險

### B1. 可投入現金雙來源不同步（報表金額互相矛盾）
- `approved_universe.deployable_twd = 2,000,000` ← `build_daily_digest` 三報顯示這個
- `multi_asset.deployable_cash_twd = 1,859,783` ← CURRENT_STATE 顯示這個（7/16 買金/結售美金後已更新）

→ 早/晚報的「可再投入」比實際多 14 萬。建議只留一個欄位（deployable_cash_twd），digest 改讀它。

### B2. TWD／黃金／加密「急跌警報」用的是快取日線，非即時價
`fetch_quote` 走 warehouse 快取（一般 TTL 36h、crypto 1h），fx_gold ingest 平日僅 4 次。「台幣單日急貶 ≥0.4%」可能延遲數小時才觸發，與 AGENTS.md「daily real-time」的定位不符。
建議：FX/黃金 TTL 降到 2–4h，或 shock 類檢查改 `TWSTOCKALS_SKIP_CACHE` 即時抓。

### B3. `scan_black_swan.py` 的 `OTC_CODES` 硬編碼
新買進上櫃標的若不在名單內，即時報價會用錯 `tse_` prefix 而抓不到。建議在 `my_targets` 加 `market: "OTC"` 欄位，或用 TPEX API 動態判別。

### B4. digest 24h 滑窗去重可能吃掉整份日報
digest 的 dedupe 是 rule_id 24 小時冷卻。若某日 cron 比前一日**早幾分鐘**觸發（GH cron 抖動），當日日報會被判定重複而不發。建議 DIGEST 類改「每日一次」判定（比對日期），不用滑窗。

### B5. 文件與實際排程不一致
- README／CLOUD_ALERTS／AGENTS 多處說 `scan_position_levels` 在 **14:15**，實際已併入 13:45 digest_close。
- `crypto_noon`（12:00）與 `preopen_core_ops`（08:30）規則存在、CURRENT_STATE 也提及，但**雲端 alerts.yml 沒有對應 cron**——若靠本機排程，請確認仍在跑。
- 佐證：`reports/history/` 的本機 black_swan 掃描檔最後一筆是 **07-16 08:45**，07-17（週五）整天沒有 → 本機排程可能已停，建議檢查 Windows 工作排程器。

### B6. `stamp_stale_portfolio_report` 潛在 banner 疊加 bug ＋ 死邏輯
移除舊 banner 的 regex 找的是「完整日報請重跑」，但它自己寫入的新 banner 是「完整日報已封存」→ 永遠移不掉，每次 sync 會再疊一層 CAUTION（目前該檔不存在所以未發作）。另 `if looks_stale or True:` 為死邏輯。

---

## C. 低風險／小項

- `ingest_common.crypto_codes()` 讀 `item["code"]`，但 `my_targets` 的 crypto 用 `symbol` 欄位 → 清單永遠 fallback 成 `["BTC-USD","ETH-USD"]`，BNB/POL 不會被 ingest（現況影響小）。
- `run_all_alerts.py` 的 `--no-popup` 定義為 `action="store_true", default=True` → 旗標永遠為 True，本機想開彈窗也開不了；且 `trigger_desktop_alert` 用 `ctypes.windll`，在 Linux 上若真的觸發會 crash。
- `eval_market_events.py` 警報文案有簡體字「急跌中不追**买**」。
- `scan_black_swan.in_close_confirm_window()` 定義後未使用（close_confirm 只認 CLI 旗標）。
- `reports/history/` 無保留策略，black_swan 每次執行都留檔（一週 30+ 檔），Google Drive 同步負擔漸增；建議 sync 時自動清 14–30 天前的檔。
- `market_data.fetch_yahoo_daily` 用本地時區 `fromtimestamp` 轉日期，TZ=Asia/Taipei 下美股資料日期可能比 Stooq 位移一天（僅備援源，低影響）。

---

## 做得好的地方

- 密鑰處理正確：`config/api_keys.json` 已 gitignore，雲端由 Secrets 動態生成。
- 事件 edge 去重（event_bus）＋ event_digest 降噪模型完整，盤中不殺阿呆谷的紀律在程式層有落實（個股停損只在 close_confirm 推）。
- cleared_positions 在 scan/levels/notify 多層防呆，避免對已出清標的推播。
- 時區統一走 `tw_time.py`，不依賴 runner 本地時區。
