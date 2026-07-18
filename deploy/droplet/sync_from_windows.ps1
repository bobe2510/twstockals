# Sync local repo → Droplet (excludes secrets cache noise; copies api_keys if present).
# Usage (PowerShell from repo root):
#   .\deploy\droplet\sync_from_windows.ps1 -HostName twstockals-do
#   .\deploy\droplet\sync_from_windows.ps1 -HostName 1.2.3.4 -User brian

param(
  [Parameter(Mandatory = $true)][string]$HostName,
  [string]$User = "brian",
  [string]$RemotePath = "/home/brian/twstockals"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Target = "${User}@${HostName}:${RemotePath}"

Write-Host "Sync $Root -> $Target"

# Ensure remote dir
ssh "${User}@${HostName}" "mkdir -p '$RemotePath'"

# Prefer scp recursive of key trees (rsync may be absent on Windows)
$exclude = @(
  ".git",
  ".venv",
  "__pycache__",
  "market_crawled_cache",
  "reports/history",
  "reports/archive",
  "*.pyc"
)

# Use tar-over-ssh for reliable sync without rsync
$tarArgs = @(
  "-C", $Root,
  "--exclude=.git",
  "--exclude=.venv",
  "--exclude=__pycache__",
  "--exclude=market_crawled_cache",
  "--exclude=reports/history",
  "--exclude=reports/archive",
  "-czf", "-",
  "."
)

Write-Host "Uploading via tar|ssh ..."
& tar @tarArgs | ssh "${User}@${HostName}" "mkdir -p '$RemotePath' && tar -xzf - -C '$RemotePath'"

# Explicitly push secrets if local file exists (not in git)
$keys = Join-Path $Root "config\api_keys.json"
if (Test-Path $keys) {
  Write-Host "Uploading config/api_keys.json ..."
  scp $keys "${User}@${HostName}:${RemotePath}/config/api_keys.json"
}

Write-Host "Done. SSH and run bootstrap if first time:"
Write-Host "  ssh ${User}@${HostName}"
Write-Host "  cd $RemotePath && bash deploy/droplet/bootstrap.sh"
