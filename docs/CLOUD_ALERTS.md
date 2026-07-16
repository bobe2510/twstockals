# 免費雲端自動提醒佈建（GitHub Actions）

Heroku 免費方案已結束。本專案改用 **GitHub Actions 定時執行**（類似排程型 PaaS，不必開著家裡電腦）。

## 會自動提醒什麼

| 模式 | 內容 |
|------|------|
| **preopen** | 約 **08:30**：若前一日 ~14:15 EOD 有 **0050／正2** 建議操作 → 開盤前提醒（無待辦不推） |
| **intraday** | 約 09:05：大盤／匯率等（**不推個股破防守**） |
| **multi_day** | 約 **10:30**、**15:00**：黃金／外匯（≥門檻請買進｜台銀可執行） |
| **crypto_noon** | 約 **12:00**（每天）：**BTC／ETH**；僅急跌／破 50MA 才推（偏重不加碼） |
| **close_confirm** | 約 **13:10**：輕量刷新 `levels.json`＋近收盤破防守＋**出清倉**停損停利（有動作才推）；**不含**完整 EOD／觀測買點 |
| **close_confirm --backup** | 約 **13:15**：同上備援；若今日 13:10 已跑過則**略過**（降噪） |
| **eod** | 約 **14:15**：刷新 levels＋持股停損停利／出清＋台股／美股 ≥門檻請買進（並寫入隔日 preopen） |
| **multi** | 約 **20:30**：黃金複核＋**BTC／ETH 破季線可減**＋美股觀測＋觀測評等 |

推播規則（混合制）：報告維持真實 D/C/B/A/S；僅當評等 ≥ [`config/grade_buy_policy.json`](../config/grade_buy_policy.json) 的 `buy_min_grade` 才推買。語氣依回測級距：

| 相對門檻 | 推播用詞 |
|----------|----------|
| = 門檻 | **允許買進（回測可買級｜非必須）** |
| 高於門檻 | **建議買進（回測較優級）** |
| 評等 S | **強烈建議買進（回測實證高）** |
| ladder 下一階 | **請加碼** |

`us_ib_go`（匯款 IB）同樣須達門檻（VOO／VXUS ≥S、QQQ ≥B），不會因「靠近年線」就催匯款。

統一入口：`python src_scripts/run_all_alerts.py --mode all|intraday|close_confirm|eod|multi_day|multi --force`  
排程**不**帶 `--force-notify`（保留 `alert_state` 去重）；手動除錯才加。

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

4. **Actions** 分頁啟用 workflows；可按 **Run workflow** 手動測 `mode=multi` 或 `all`。

5. 確認 `config/my_targets.json`、`config/alert_rules.json` 有進 repo（不含密鑰）。

## 排程（台北時間 Asia/Taipei = UTC+8）

GitHub `cron` 用 **UTC**；程式內時間窗／推播時間戳一律用 `Asia/Taipei`（`src_scripts/tw_time.py`），並設 `TZ=Asia/Taipei`。

| 台北時間 | UTC cron | mode |
|---------|----------|------|
| 平日 ~08:30 | `30 0 * * 1-5` | preopen |
| 平日 ~09:05 | `5 1 * * 1-5` | intraday |
| 平日 ~10:30 | `30 2 * * 1-5` | multi_day |
| 每天 ~12:00 | `0 4 * * *` | crypto_noon |
| 平日 ~13:10 | `10 5 * * 1-5` | close_confirm |
| 平日 ~13:15 | `15 5 * * 1-5` | close_confirm `--backup` |
| 平日 ~14:15 | `15 6 * * 1-5` | eod |
| 平日 ~15:00 | `0 7 * * 1-5` | multi_day |
| 每天 ~20:30 | `30 12 * * *` | multi |

門檻速記（詳見 `grade_buy_policy.json`）：黃金 ≥B；美金／BTC ≥A；0050／正2／QQQ ≥B；VOO／VXUS ≥S。  
可動用現金預設 **200 萬＝既有持倉之外可再投入的新增現金**；其中約 **25% 機會準備金**（美金／VOO／VXUS），其餘常態池（黃金／0050／正2／QQQ）；推播會帶**剩餘機會金**。  
0050／黃金等為 flat（達門檻進場一次）；僅 QQQ／QQQM 用 ladder 分階加碼。

`pause_us_ib=true` 時：**不推**美股買點／「請匯款 IB」；報告仍可觀測。

Alert／階梯進度：`reports/alert_state.json`、`deploy_ladder_state.json`、`eod_pending_ops.json`、`close_confirm_ran.json` 以 Actions cache 盡量保留。

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
