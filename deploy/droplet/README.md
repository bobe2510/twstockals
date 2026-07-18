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

## F. 單向拉取報告（本機讀 Droplet 產出）

只拉 `reports/latest`（不動程式／金鑰／倉）：

```powershell
.\deploy\droplet\pull_reports_latest.ps1 -HostName twstockals-do
```

每 30 分自動拉一次（Windows 工作排程）：

```powershell
.\deploy\droplet\register_pull_reports_task.ps1 -HostName twstockals-do -Minutes 30
```

取消：`Unregister-ScheduledTask -TaskName twstockals-pull-reports-latest -Confirm:$false`

---

## 故障

```bash
journalctl -u 'twstockals-alert@digest_am' -n 80 --no-pager
journalctl -u 'twstockals-ingest@crypto' -n 80 --no-pager
```
