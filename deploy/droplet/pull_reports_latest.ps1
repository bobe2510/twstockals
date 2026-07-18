# One-way pull: Droplet reports/latest → local reports/latest
# Usage:
#   .\deploy\droplet\pull_reports_latest.ps1 -HostName twstockals-do
#   .\deploy\droplet\pull_reports_latest.ps1 -HostName 1.2.3.4 -User brian
#
# Schedule: .\deploy\droplet\register_pull_reports_task.ps1 -HostName twstockals-do -Minutes 30

param(
  [Parameter(Mandatory = $true)][string]$HostName,
  [string]$User = "brian",
  [string]$RemotePath = "/home/brian/twstockals",
  [string]$LocalLatest = ""
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $LocalLatest) {
  $LocalLatest = Join-Path $Root "reports\latest"
}

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-Host "[$stamp] Pull ${User}@${HostName}:${RemotePath}/reports/latest -> $LocalLatest"

New-Item -ItemType Directory -Force -Path $LocalLatest | Out-Null
$tmpTar = Join-Path $env:TEMP ("twstockals_reports_latest_{0}.tgz" -f (Get-Date -Format "yyyyMMddHHmmss"))
if (Test-Path $tmpTar) { Remove-Item $tmpTar -Force }

$sshTarget = "${User}@${HostName}"
$remote = "cd '$RemotePath' && tar -czf - -C reports latest"

# ssh stdout → local tarball (cmd redirect handles binary on Windows)
cmd /c "ssh -o BatchMode=yes $sshTarget `"$remote`" > `"$tmpTar`""
$okTar = (Test-Path $tmpTar) -and ((Get-Item $tmpTar).Length -gt 64)

if ($okTar) {
  $reportsParent = Join-Path $Root "reports"
  New-Item -ItemType Directory -Force -Path $reportsParent | Out-Null
  Push-Location $reportsParent
  try {
    tar -xzf $tmpTar
  } finally {
    Pop-Location
    Remove-Item $tmpTar -Force -ErrorAction SilentlyContinue
  }
} else {
  Write-Host "tar pull failed; falling back to scp -r ..."
  if (Test-Path $tmpTar) { Remove-Item $tmpTar -Force -ErrorAction SilentlyContinue }
  $remoteSpec = "${sshTarget}:${RemotePath}/reports/latest/."
  scp -o BatchMode=yes -r $remoteSpec "$LocalLatest\"
}

$n = (Get-ChildItem $LocalLatest -File -ErrorAction SilentlyContinue | Measure-Object).Count
Write-Host "[$stamp] Done. files in latest ≈ $n"
