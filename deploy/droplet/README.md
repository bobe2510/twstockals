# DigitalOcean Droplet 部署（使用者 `brian`）

路徑預設：`/home/brian/twstockals`  
推播模型：`event_digest`（07:30／13:45／19:00＋事件）＋ ingest timers。  
詳見 [`docs/DATA_INGEST.md`](../../docs/DATA_INGEST.md)、[`docs/EVENT_DRIVEN_ALERTS_PLAN.md`](../../docs/EVENT_DRIVEN_ALERTS_PLAN.md)。

---

## A. 本機（Windows）上傳專案

在 repo 根目錄 PowerShell：

```powershell
# HostName 用 ssh config 別名（如 twstockals-do）或 IP
.\deploy\droplet\sync_from_windows.ps1 -HostName twstockals-do -User brian
```

會上傳程式與（若存在）`config/api_keys.json`，排除 `.venv`／大型 cache。

---

## B. Droplet 上首次安裝

```bash
ssh brian@YOUR_HOST
cd ~/twstockals
bash deploy/droplet/bootstrap.sh
# 若 api_keys 是空範本，先填：
nano config/api_keys.json
# 確認持股設定存在
ls config/my_targets.json

# 安裝 systemd（需 sudo）
sudo TWSTOCKALS_WORKSPACE=/home/brian/twstockals TWSTOCKALS_USER=brian \
  bash deploy/droplet/install_timers.sh

# 煙測
.venv/bin/python src_scripts/run_ingest.py --job crypto --no-notify
.venv/bin/python src_scripts/run_all_alerts.py --mode digest_am --force --no-ingest
systemctl list-timers 'twstockals-*' --no-pager
```

---

## C. 排程一覽（Asia/Taipei）

| Timer | 時間 | 動作 |
|-------|------|------|
| digest-am | 每天 07:30 | 早報 |
| scan-bg | 平日 10:30 | 背景事件 |
| close-confirm | 平日 13:10 | 收盤確認（寫事件） |
| close-confirm-backup | 平日 13:25 | 備援（今日已跑過即跳過） |
| digest-close | 平日 13:45 | 收盤執行報 |
| digest-pm | 每天 19:00 | 晚報 |
| ingest-* | 見 DATA_INGEST | 資料倉 |
| ingest-health | 每小時 :05 | 倉健康 |

---

## D. 與 GitHub Actions

部署並確認 Telegram 有收到 Droplet 推播後，到 GitHub **Disable** `twstockals-alerts`／`twstockals-ingest`（或 Settings→Actions→Disable）。

---

## E. 更新程式

本機改完再：

```powershell
.\deploy\droplet\sync_from_windows.ps1 -HostName twstockals-do
```

Droplet：

```bash
cd ~/twstockals
source .venv/bin/activate
pip install -r requirements.txt   # 若有新依賴
# timers 通常不必重裝；改過 .service 才重跑 install_timers.sh
```

---

## F. Google Drive 雙向同步（2026-07-19 起，取代 SSH 拉取／推送）

Droplet 用 rclone（`~/.local/bin/rclone`，OAuth 個人授權＋root_folder_id 鎖定 `dev/twstockals`）
直接與 Google Drive 同步；Windows 端靠 Drive 桌面版自動收發，**不再需要本機排程**。

兩條不相交的單向同步（誰是作者誰推）：

| Timer | 頻率 | 方向 | 內容 |
|-------|------|------|------|
| gdrive-pull | 每 10 分（:00） | Drive → Droplet | 程式＋config（排除 reports/、.git/、.venv/、快取） |
| gdrive-push | 每 10 分（:05） | Droplet → Drive | reports/ 全部 |

安裝（Droplet 上）：

```bash
cd /home/brian/twstockals && sudo bash deploy/droplet/install_gdrive_sync.sh
```

授權失效重連（本機先開 tunnel `ssh -L 53682:localhost:53682 twstockals-do`）：

```bash
printf 'y\ny\n' | ~/.local/bin/rclone config reconnect gdrive:
```

> 舊機制備援：`pull_reports_latest.ps1`／`register_pull_reports_task.ps1`（SSH 拉取）與
> `sync_from_windows.ps1`（SSH 推送）保留可用；已註冊的 Windows 排程請取消：
> `Unregister-ScheduledTask -TaskName twstockals-pull-reports-latest -Confirm:$false`

---

## 故障

```bash
journalctl -u 'twstockals-alert@digest_am' -n 80 --no-pager
journalctl -u 'twstockals-ingest@crypto' -n 80 --no-pager
```
