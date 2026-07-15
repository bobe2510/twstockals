# 免費雲端自動提醒佈建（GitHub Actions）

Heroku 免費方案已結束。本專案改用 **GitHub Actions 定時執行**（類似排程型 PaaS，不必開著家裡電腦）。

## 會自動提醒什麼

| 模式 | 內容 |
|------|------|
| **intraday** | 約 09:05：大盤／匯率等（**不推個股破防守**） |
| **close_confirm** | 約 **13:10**：近收盤確認破防守＋提早清單＋**觀測評等（0050／正2等）** |
| **eod** | 約 14:15：完整收盤停損停利／出清 |
| **multi** | 約 20:00：黃金＋匯率＋BTC＋美股＋**再跑一遍觀測評等** |

統一入口：`python src_scripts/run_all_alerts.py --mode all|intraday|eod|multi --force`

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

## 排程（台北時間）

- 平日約 07–14 點：每小時 intraday  
- 平日約 14:15：eod  
- 每天約 20:00：multi（黃金／匯率／加密／美股觀測）

## 限制（免費方案誠實說明）

- GitHub Actions 免費額度對私人 repo 有月分鐘上限（一般個人夠用）
- 排程可能延遲數分鐘
- 無長駐磁碟：`alert_state` 用 cache 盡量去重，不保證完美
- 大檔 `market_crawled_cache` 不上傳；雲端以即時 Yahoo／證交所 API 為主

## 本機仍可雙軌

家裡電腦想跑也可以：

```bash
python src_scripts/run_all_alerts.py --mode multi --force
```

雲端＋本機同時跑時，靠 `alert_state`／規則冷卻減少重複推播；若覺得吵，關掉本機排程即可。
