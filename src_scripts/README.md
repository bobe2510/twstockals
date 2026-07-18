# 活躍執行腳本（持倉監控優先）

日常只認：**`config/my_targets.json`**（持股真相）＋雲端推播鏈。  
台股全市場選股／社群股／OCR／舊持股深報已移到 `legacy/`。

## 日常入口

```bash
python src_scripts/run_all_alerts.py --mode digest_am|digest_close|digest_pm|scan_bg|close_confirm|eod|multi --force
python src_scripts/sync_runtime_state.py          # 對齊 holdings／CURRENT_STATE、清過期 pending
python src_scripts/refresh_levels_live.py         # 輕量刷新現價／均線／停損參考
```

詳見 [`docs/CLOUD_ALERTS.md`](../docs/CLOUD_ALERTS.md)。

## 主線腳本

| 腳本 | 用途 |
|------|------|
| `run_all_alerts.py` | 雲端／本機統一入口 |
| `sync_runtime_state.py` | 持股 scrub、CURRENT_STATE |
| `refresh_levels_live.py` | 現價 levels |
| `scan_black_swan.py` | 盤中大盤／匯率；13:10 破防守 |
| `scan_exit_watch.py` | 13:10 出清倉（美債 gradual_exit、個股殘倉） |
| `scan_position_levels.py` | 13:45 digest_close 內 EOD 停損停利 |
| `scan_watch_grades.py` | 觀測評等請買進 |
| `scan_multi_asset.py` | 黃金／外匯／BTC／ETH／美股觀測 |
| `notify.py` / `grade_buy_policy.py` / `holding_rules.py` / `trade_levels.py` / `market_data.py` / `tw_time.py` / `eod_pending_ops.py` | 共用庫 |
| `fetch_stock_data.py` | 手動補單一標的 K 線 |
| `research/run_*_backtest.py` | 少跑：校準 CP／買點門檻（產出在 `reports/latest/backtest/`） |

## 出清倉仍會抓

`my_targets.portfolio` 裡帶 `policy: gradual_exit`（如 **00687B**）與個股殘倉（以 `my_targets.json` 現況為準；不新開個股）會進：

- `refresh_levels_live`（現價）
- `scan_exit_watch`（13:10）
- `scan_position_levels`（13:45 digest_close 內）

## 設定

| 檔案 | 用途 |
|------|------|
| `config/my_targets.json` | **唯一手改**持股／已出清／現金／pause_us_ib |
| `config/alert_rules.json` | 閾值／冷卻 |
| `config/grade_buy_policy.json` | 買點門檻與金額 |

> 舊選股器／社群評分／OCR（`legacy/`）與 GitHub Actions workflows 已於 2026-07 精簡移除；需要時從 git 歷史找回。
