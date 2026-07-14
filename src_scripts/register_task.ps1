# Find run_scan.vbs path dynamically
$scriptDir = $PSScriptRoot
if (-not $scriptDir) {
    $scriptDir = Get-Location
}

$vbsPath = Join-Path $scriptDir "run_scan.vbs"
if (-not (Test-Path $vbsPath)) {
    $vbsPath = Join-Path $scriptDir "src_scripts\run_scan.vbs"
}
if (-not (Test-Path $vbsPath)) {
    $parent = Split-Path $scriptDir -Parent
    $vbsPath = Join-Path $parent "src_scripts\run_scan.vbs"
}

if (-not (Test-Path $vbsPath)) {
    Write-Error "run_scan.vbs not found, check path!"
    exit 1
}

$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbsPath`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "TWStockBlackSwanScan" -Action $action -Trigger $trigger -Force
Write-Host "Task registered successfully with path: $vbsPath"
