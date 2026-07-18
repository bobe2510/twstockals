# 一次性專案精簡腳本（2026-07-18 健檢後）— 在 repo 根目錄執行：
#   powershell -ExecutionPolicy Bypass -File .\cleanup_project.ps1
# 完成後可自行刪除本檔。使用 $PSScriptRoot 動態路徑（勿硬編碼中文路徑）。

$ErrorActionPreference = "Stop"
$WS = $PSScriptRoot
Write-Host "Workspace: $WS"

# ---------- 1. 刪除（已核准範圍） ----------
$toDelete = @(
    "src_scripts\legacy",
    "reports\archive",
    "raw_collected_news",
    ".github",
    "config\archive"
)
foreach ($rel in $toDelete) {
    $p = Join-Path $WS $rel
    if (Test-Path $p) {
        Remove-Item -Recurse -Force $p
        Write-Host "DELETED  $rel"
    } else {
        Write-Host "SKIP(no) $rel"
    }
}

# ---------- 2. 回測腳本 → src_scripts\research\ ----------
$research = Join-Path $WS "src_scripts\research"
New-Item -ItemType Directory -Force -Path $research | Out-Null
$btScripts = @(
    "run_etf_backtest.py",
    "run_grade_threshold_backtest.py",
    "run_grade_ladder_backtest.py",
    "run_shortlist_backtest.py",
    "run_momentum_hybrid_backtest.py",
    "run_playbook_revision_backtest.py"
)
foreach ($f in $btScripts) {
    $src = Join-Path $WS "src_scripts\$f"
    if (Test-Path $src) {
        Move-Item -Force $src (Join-Path $research $f)
        Write-Host "MOVED    src_scripts\$f -> src_scripts\research\"
    }
}

# ---------- 3. 回測產出／一次性報告 → reports\latest\backtest\ ----------
$btOut = Join-Path $WS "reports\latest\backtest"
New-Item -ItemType Directory -Force -Path $btOut | Out-Null
$latest = Join-Path $WS "reports\latest"
$btFiles = @(
    "etf_backtest_report.md", "strategy_cp_ranking.md", "strategy_cp_best.json",
    "grade_threshold_backtest.md", "grade_threshold_backtest.json",
    "grade_ladder_backtest.md", "grade_ladder_best.json",
    "shortlist_backtest.md", "shortlist_backtest.json",
    "momentum_hybrid_backtest.md", "momentum_hybrid_backtest.json",
    "playbook_revision_backtest.md", "playbook_revision_backtest.json"
)
foreach ($f in $btFiles) {
    $src = Join-Path $latest $f
    if (Test-Path $src) {
        Move-Item -Force $src (Join-Path $btOut $f)
        Write-Host "MOVED    reports\latest\$f -> backtest\"
    }
}
Get-ChildItem -Path $latest -Filter "crisis_review_*.md" -File -ErrorAction SilentlyContinue |
    ForEach-Object {
        Move-Item -Force $_.FullName (Join-Path $btOut $_.Name)
        Write-Host "MOVED    reports\latest\$($_.Name) -> backtest\"
    }

# ---------- 4. reports\history 保留 30 天（之後由 sync_runtime_state 自動清） ----------
$hist = Join-Path $WS "reports\history"
if (Test-Path $hist) {
    $cutoff = (Get-Date).AddDays(-30)
    Get-ChildItem -Path $hist -File | Where-Object { $_.LastWriteTime -lt $cutoff } |
        ForEach-Object {
            Remove-Item -Force $_.FullName
            Write-Host "PRUNED   history\$($_.Name)"
        }
}

Write-Host ""
Write-Host "完成。後續："
Write-Host "  1) 用 deploy\droplet\sync_from_windows.ps1 同步到 droplet"
Write-Host "  2) droplet 上重跑 install_timers.sh（新增 close-confirm-backup timer）"
Write-Host "  3) git add -A; git commit（若仍有 git repo）"
Write-Host "  4) 刪除本腳本 cleanup_project.ps1"
