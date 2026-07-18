# Register Windows Scheduled Task: pull reports/latest every N minutes.
#   .\deploy\droplet\register_pull_reports_task.ps1 -HostName twstockals-do
#   .\deploy\droplet\register_pull_reports_task.ps1 -HostName twstockals-do -Minutes 30

param(
  [Parameter(Mandatory = $true)][string]$HostName,
  [string]$User = "brian",
  [int]$Minutes = 30,
  [string]$TaskName = "twstockals-pull-reports-latest"
)

$ErrorActionPreference = "Stop"
$Script = (Resolve-Path (Join-Path $PSScriptRoot "pull_reports_latest.ps1")).Path
$Arg = "-NoProfile -ExecutionPolicy Bypass -File `"$Script`" -HostName $HostName -User $User"

# Remove broken prior registration if any
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $Arg
# Windows rejects TimeSpan.MaxValue (P99999999DT23H59M59S). Use ~10 years.
$trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) `
  -RepetitionInterval (New-TimeSpan -Minutes $Minutes) `
  -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
  -Settings $settings -Force | Out-Null

Write-Host "Registered task '$TaskName' every $Minutes min -> $HostName"
Write-Host "Test now:  schtasks /Run /TN `"$TaskName`""
Write-Host "Remove:    Unregister-ScheduledTask -TaskName `"$TaskName`" -Confirm:`$false"
