[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$TaskName = "FinQuery Daily Data Update",
    [datetime]$At = "03:00",
    [string]$PythonPath
)

$ErrorActionPreference = "Stop"
$backendPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $PythonPath = Join-Path $backendPath ".venv\Scripts\python.exe"
}
$resolvedPython = (Resolve-Path $PythonPath).Path
$arguments = '-m scripts.update_curated_data'
$currentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$currentPrincipal = New-Object System.Security.Principal.WindowsPrincipal($currentIdentity)
$isAdministrator = $currentPrincipal.IsInRole(
    [System.Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $WhatIfPreference -and -not $isAdministrator) {
    throw "Administrator privileges are required to register an S4U task. Reopen PowerShell as Administrator and run this script again."
}

$action = New-ScheduledTaskAction `
    -Execute $resolvedPython `
    -Argument $arguments `
    -WorkingDirectory $backendPath
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 8) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal `
    -UserId $currentIdentity.Name `
    -LogonType S4U `
    -RunLevel Limited

if ($PSCmdlet.ShouldProcess($TaskName, "Register daily data update task")) {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Incrementally update, validate, and compact FinQuery curated market data." `
        -Force | Out-Null

    Write-Host "Scheduled task '$TaskName' installed. It runs daily at $($At.ToString('HH:mm'))."
}
Write-Host "The task can run while this user is logged off. Logs: $backendPath\logs"
