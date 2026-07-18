# 雲端自動提醒佈建

> [!NOTE]
> **2026-07 起主節點＝DigitalOcean Droplet**（systemd timers，佈建見 [`deploy/droplet/README.md`](../deploy/droplet/README.md)）。
> **GitHub Actions workflows 已停用**，本文的 Actions 章節僅留作備援參考。

來源矩陣、ingest、cutover 見 [`docs/DATA_INGEST.md`](DATA_INGEST.md)。

## 會自動提醒什麼（event_digest 模型）

詳見 [`docs/EVENT_DRIVEN_ALERTS_PLAN.md`](EVENT_DRIVEN_ALERTS_PLAN.md)。`alert_rules.notify_mode=event_digest` 時，例行 scan **不推播**；只推：

### 固定三報（台北）

| 模式 | 時間 | 內容 |
|------|------|------|
| **digest_am** | **07:30** | 部位／資金／進行中事件／待辦 |
| **digest_close** | **13:45**（交易日） | 收盤確認後必做＋事件；假日略過 |
| **digest_pm** | **19:00** | 全日收斂＋美股／加密視窗 |

### 事件推播（edge；持續不重複）

| 事件 | 開始 | 結束 |
|------|------|------|
| 大盤 Level 變更 | 推 | 推（降級／回 L1） |
| TWD 急貶 ≥0.4% | 推（當日 1 次） | **不推** |
| 核心個股收盤破防守 | 推 | 推（**兩日**站回） |
| 正2／大盤破年線 | 推 | 推（**一日**站回） |
| 金／BTC／ETH 急跌（持倉或可買；幣須＜50MA） | 推（當日 1 次） | **不推** |
| ingest 連續失敗 ≥2 | 推 | 推（連續成功 ≥2） |

背景：`close_confirm`（13:10／13:15）、`scan_bg`（約 10:30）只更新報告／`event_state`，有 edge 才推。

統一入口：

```bash
python src_scripts/run_all_alerts.py --mode digest_am|digest_close|digest_pm|scan_bg|close_confirm --force
```

排程**不**帶 `--force-notify`。觀測評等／ladder 加碼文案改入三報，不再單獨吵推。

## 佈建步驟

1. 在 GitHub 新建 **Private** repository（建議私有，因含持股設定）
2. 本機初始化並推送（若尚未是 git repo）：

```bash
cd twstockals
git init
git add .
git commit -m "Add cloud alerts via GitHub Actions"
git branch -M main
git remote add origin https://github.com/<你的帳號>/<repo>.git
git push -u origin main
```

注意：`config/api_keys.json` 已被 `.gitignore` 排除，**不要**推上 GitHub。

3. Repo → **Settings → Secrets and variables → Actions → New repository secret** 新增：

| Secret | 說明 |
|--------|------|
| `TELEGRAM_BOT_TOKEN` | BotFather token |
| `TELEGRAM_CHAT_ID` | 你的 chat id |
| `SMTP_USER` | Gmail |
| `SMTP_PASSWORD` | Gmail 應用程式密碼 |
| `SMTP_TO` | 收信信箱 |
| `SMTP_HOST` | 可選，預設用程式內 smtp.gmail.com |
| `SMTP_PORT` | 可選，587 |
| `FINMIND_TOKENS` | 可選；JSON 陣列或換行分隔（供警報前 ingest／[`ingest.yml`](../.github/workflows/ingest.yml)） |
| `TIINGO_API_KEY` | 可選；美股備援 |

4. **Actions** 分頁啟用 workflows；可按 **Run workflow** 手動測 `mode=multi` 或 `all`。

5. 確認 `config/my_targets.json`、`config/alert_rules.json` 有進 repo（不含密鑰）。

## 排程（台北時間 Asia/Taipei = UTC+8）

GitHub `cron` 用 **UTC**；程式內時間窗／推播時間戳一律用 `Asia/Taipei`（`src_scripts/tw_time.py`），並設 `TZ=Asia/Taipei`。

| 台北時間 | UTC cron | mode |
|---------|----------|------|
| 每天 ~07:30 | `30 23 * * *` | digest_am |
| 平日 ~10:30 | `30 2 * * 1-5` | scan_bg |
| 平日 ~13:10 | `10 5 * * 1-5` | close_confirm（寫事件） |
| 平日 ~13:15 | `15 5 * * 1-5` | close_confirm `--backup` |
| 平日 ~13:45 | `45 5 * * 1-5` | digest_close |
| 每天 ~19:00 | `0 11 * * *` | digest_pm |

門檻速記（詳見 `grade_buy_policy.json`）：黃金 ≥B；美金／BTC ≥A；0050／正2／QQQ ≥B；VOO／VXUS ≥S。  
可動用現金預設 **200 萬＝既有持倉之外可再投入的新增現金**；其中約 **25% 機會準備金**（美金／VOO／VXUS），其餘常態池（黃金／0050／正2／QQQ）；推播會帶**剩餘機會金**。  
0050／黃金等為 flat（達門檻進場一次）；僅 QQQ／QQQM 用 ladder 分階加碼。

`pause_us_ib=true` 時：**不推**美股買點／「請匯款 IB」；報告仍可觀測。

Alert／階梯進度：`reports/alert_state.json`、`deploy_ladder_state.json`、`eod_pending_ops.json`、`close_confirm_ran.json` 以 Actions cache 盡量保留。

**防過期**：每次 `close_confirm`／`eod` 會先跑 `sync_runtime_state.py`，以 `my_targets.json` scrub `levels`／`holdings`、清空矛盾 pending，並寫入 `reports/latest/CURRENT_STATE.md`。決策以該檔與當日 EOD 為準。

**出清倉持續監控**：`my_targets.portfolio` 中的 `gradual_exit`（如 00687B）與個股殘倉會在 13:10 `close_confirm`（scan_exit_watch）、13:45 `digest_close`（scan_position_levels）繼續抓價與推播；選股腳本移入 `legacy/` **不影響**這條鏈。

選股／舊持股深報已於 2026-07 精簡移除（需要時從 git 歷史找回）。

## 限制（免費方案誠實說明）

- GitHub Actions 免費額度對私人 repo 有月分鐘上限（一般個人夠用）
- 排程可能延遲數分鐘
- 無長駐磁碟：`alert_state` 用 cache 盡量去重，不保證完美
- 大檔 `market_crawled_cache` 不上傳；雲端以即時 Yahoo／證交所 API 為主；EOD／收盤確認前會跑 `refresh_levels_live.py` 輕量刷新現價

## 本機仍可雙軌

家裡電腦想跑也可以：

```bash
python src_scripts/run_all_alerts.py --mode multi --force
```

雲端＋本機同時跑時，靠 `alert_state`／規則冷卻減少重複推播；若覺得吵，關掉本機排程即可。
