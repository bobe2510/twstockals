# 報告目錄

## `latest/`（日常）

決策只看這些（由推播鏈／`sync_runtime_state` 產生，勿手改）：

| 檔案 | 用途 |
|------|------|
| `CURRENT_STATE.md` | 現行持股摘要（對齊 my_targets） |
| `holdings.json` | 持股快照（僅 sync 寫入） |
| `levels.json` | 現價／停損參考 |
| `eod_action_list.md` | 收盤執行清單 |
| `eod_pending_ops.json` | EOD 待辦（進隔日早報） |
| `black_swan_defense.md` | 大盤／匯率 |
| `exit_watch_1310.md` | 出清倉 13:10 |
| `digest_am.md` / `digest_close.md` / `digest_pm.md` | 固定三報 |
| `watch_grades.md` / `multi_asset_levels.md` | 各模式產出 |
| `backtest/` | 回測產出（少跑） |

## `history/`

黑天鵝等自動時間戳備份（sync 自動保留 30 天）。
