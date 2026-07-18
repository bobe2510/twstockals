# twstockals

台股／多資產：**持倉監控＋停損停利推播**（Telegram／Email）。
雲端主節點：**DigitalOcean Droplet**（systemd timers，見 [`deploy/droplet/`](deploy/droplet/)）；GitHub Actions 已停用（僅留備援設定）。

## 你日常只碰這些

1. 改持股／現金／是否暫停 IB → [`config/my_targets.json`](config/my_targets.json)
2. 看現況 → [`reports/latest/CURRENT_STATE.md`](reports/latest/CURRENT_STATE.md) + 當日 `eod_action_list.md`
3. 推播排程說明 → [`docs/CLOUD_ALERTS.md`](docs/CLOUD_ALERTS.md)

```bash
python src_scripts/sync_runtime_state.py
python src_scripts/run_all_alerts.py --mode eod --force
```

## 出清倉會繼續監控

`portfolio` 內的 `gradual_exit`（如 00687B）與個股殘倉會進 13:10 `close_confirm`（scan_exit_watch）與 13:45 `digest_close`（scan_position_levels）掃描，不會因簡化而停抓。

## 目錄

| 路徑 | 用途 |
|------|------|
| `src_scripts/` | 活躍推播腳本 |
| `src_scripts/research/` | 回測／校準腳本（少跑，不進排程） |
| `reports/latest/` | 當日執行產物 |
| `reports/latest/backtest/` | 回測產出 |
| `deploy/droplet/` | 雲端主節點佈建（systemd timers） |

紀律： [`.agents/DISCIPLINE.md`](.agents/DISCIPLINE.md)
