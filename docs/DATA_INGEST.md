# Droplet 資料倉：來源矩陣、額度與排程

本文件對應 DigitalOcean Droplet 上的 **ingest → 本地倉 → 掃描器讀倉** 流程。警報與 ingest 解耦：先抓數成功，再跑 scan。

統一入口：`python src_scripts/run_ingest.py --job all|tw_eod|us_eod|fx_gold|crypto`

倉位根目錄：`market_crawled_cache/warehouse/`（gitignore，不上傳 GitHub）。

## 與推播連動（已接上）

| 層級 | 行為 |
|------|------|
| **警報前 pre-ingest** | `run_all_alerts.py` 預設先跑對應 job（`--no-ingest` 可關）；失敗 → Telegram／Email（`notify`，每日去重） |
| **獨立排程** | GitHub Actions [`ingest.yml`](../.github/workflows/ingest.yml)；Droplet [`deploy/droplet/`](../deploy/droplet/) |
| **健康檢查** | `check_ingest_health.py`：manifest 失敗／倉過期 → 推播 `INGEST\|health_stale` |
| **交易訊號推播** | 仍由既有 scan（破防守、買點等）負責；ingest 只負責「資料抓不到／過期」 |

Actions Secrets 建議加：`FINMIND_TOKENS`（JSON 陣列或換行分隔 4 支）、可選 `TIINGO_API_KEY`。

---

## 商品 × 來源矩陣


| 商品／資料 | 建議主來源（免費） | 備援 | 值得付費時 | 備註 |
|------------|-------------------|------|------------|------|
| 台股日線 | TWSE OpenAPI `STOCK_DAY_ALL` | FinMind `TaiwanStockPrice` | FinMind Sponsor；Fugle（盤中） | 官方當日最乾淨 |
| 大盤 TAIEX | TWSE 指數 OpenAPI | FinMind 指數日線 | 同上 | 與正2 年線規則相關 |
| 法人／融資籌碼 | FinMind（股→張／1000） | TWSE 公開 JSON | FinMind Sponsor | 完整日資料建議 ≥17:00 |
| 美股 ETF | Stooq 日線 CSV | FinMind US／Yahoo | Tiingo／Polygon | Yahoo 勿當主 |
| 黃金 | Stooq `gc.f`／Yahoo `GC=F` | Metals-API 免費層 | 台銀金價商（若誤差成問題） | ≠台銀存摺成交價 |
| USD/TWD | Stooq `usdtwd`；Frankfurter 類 | Yahoo `USDTWD=X` | Open Exchange Rates | 日線夠 EOD |
| 加密 BTC／ETH | Binance 公開 REST | Yahoo | 通常不必 | 注意 IP weight |
| 新聞／黑天鵝 | 現有 RSS／Yahoo | Google News RSS | 非必要 | 僅警報語意 |

**付費優先序：** FinMind Sponsor → Tiingo（美股）→ Fugle／券商行情（單帳）→ 台銀金價 API。

**ToS：** 勿用多帳規避券商行情條款。FinMind 多 token 輪詢為正式做法（`FINMIND_TOKENS` ×4）。

---

## FinMind token（預留 4）

免費約 **600 req／hr／token**；預留 20% → 約 **480／hr／token**。

| 槽位 | 用途 |
|------|------|
| #1～#2 | 日常輪詢 |
| #3 | 尖峰／回補 |
| #4 | 402 熱備 |

複製 [`config/api_keys.example.json`](../config/api_keys.example.json) → `config/api_keys.json`，貼上非空 token。空字串會被 rotator 略過。可選 `TIINGO_API_KEY`。

---

## 建議排程（Asia/Taipei）

| 任務 | 節奏 | Worker |
|------|------|--------|
| 台股 EOD 全市場快照 | 交易日 14:00 起每 15–30 分直到成功；17:30 籌碼補抓 | `tw_eod` |
| 美股 ETF 日線 | 美股收盤後（台北約 05:00–07:00）每日 | `us_eod` |
| 金／匯 | 銀行窗 10:00–15:30 每 20–30 分；夜間每 1–2 時 | `fx_gold` |
| 加密 | 警報窗每 5–15 分；全日可每 15 分健康檢查 | `crypto` |

systemd 單元見 [`deploy/droplet/`](../deploy/droplet/)。失敗會 Telegram（`notify.send_telegram`）。

---

## 倉優先讀取

`market_data.fetch_daily` 先讀 `warehouse/{source}/{symbol}.csv`（TTL 內），過期才打 API 並回寫。環境變數：

- `TWSTOCKALS_CACHE_TTL_HOURS`：預設日線 36
- `TWSTOCKALS_CACHE_TTL_CRYPTO_HOURS`：預設 1
- `TWSTOCKALS_SKIP_CACHE=1`：強制即時抓

---

## 相對 GitHub Actions 遷移（cutover）

1. **第 0 週：** Droplet 只跑 ingest；Actions 警報照舊。比對 `warehouse` 與 Actions 現價／levels。
2. **一週對照通過後：** 警報改讀本地倉（`fetch_daily` 倉優先）；Actions 改備援或關閉。
3. **再評估：** FinMind 402 頻繁 → Sponsor；美股 Stooq 不穩 → Tiingo。

對照檢查清單見下方「Cutover checklist」。

### Cutover checklist

- [ ] `run_ingest.py --job all` 連續成功 ≥5 個交易日
- [ ] `manifest.json` 各 job `ok=true`、列數合理
- [ ] `python src_scripts/check_ingest_cutover.py` 倉 vs 即時價差在容許範圍
- [ ] 持倉代號收盤價與券商／Yahoo 誤差可接受（ETF／金匯）
- [ ] `run_all_alerts.py --mode eod --force` 讀倉後 levels 合理
- [ ] 關閉或降頻 Actions 前確認 Telegram 仍通
- [ ] 記錄是否需要 FinMind Sponsor／Tiingo（402 頻繁 → Sponsor；Stooq 長期失敗 → Tiingo）

---

## 非目標

- 自動下單適配器
- 多帳規避券商 ToS
- 保證台銀金價＝GC=F 換算
