<#
.SYNOPSIS
    Registra las tareas automáticas de EconomicScript en el Programador de Windows.

.DESCRIPTION
    Crea tareas:
    - EconomicScript-Poll    : cada 10 min, revisa Gmail (sin alerta por TX por defecto)
    - EconomicScript-Evening : 19:00, resumen tier-1 del día + acumulado del mes (--today)
    - EconomicScript-Daily   : deshabilitada por defecto (usar solo 19:00)

.NOTES
    Ejecutar como Administrador:
    powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1
#>

$ErrorActionPreference = "Stop"

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunWrapper  = Join-Path $ScriptDir "run_task.ps1"
$PollMinutes = 10

if (-not (Test-Path $RunWrapper)) {
    Write-Error "No se encontró run_task.ps1 en: $RunWrapper"
    exit 1
}

$EnvFile = Join-Path $ScriptDir ".env"
if (-not (Test-Path $EnvFile)) {
    Write-Warning ".env no encontrado. Configura credenciales antes de que las tareas se ejecuten."
}

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit    (New-TimeSpan -Hours 1) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances     IgnoreNew `
    -RestartCount          3 `
    -RestartInterval       (New-TimeSpan -Minutes 5)

Write-Host ""
Write-Host "Configurando EconomicScript en: $ScriptDir"
Write-Host ""

$PollCmd  = Join-Path $ScriptDir "poll.cmd"
$DailyCmd = Join-Path $ScriptDir "daily.cmd"

# Importante: NO usar schtasks.exe /TR con rutas que contienen espacios
# ("T14 Gen 2", "OneDrive", …) — parte el path. Usar Register-ScheduledTask
# con Execute=cmd.exe y Argument entrecomillado.

# ── Poll cada N min ────────────────────────────────────────────────────────────
$ActionPoll = New-ScheduledTaskAction `
    -Execute          "cmd.exe" `
    -Argument         "/c `"$PollCmd`"" `
    -WorkingDirectory $ScriptDir

# Trigger por minutos via schtasks solo para el schedule; la acción se sobrescribe abajo.
# Alternativa 100% PowerShell: repetir trigger -Once -RepetitionInterval
$pollStart = (Get-Date).Date.AddMinutes(1)
$PollTrigger = New-ScheduledTaskTrigger -Once -At $pollStart `
    -RepetitionInterval (New-TimeSpan -Minutes $PollMinutes) `
    -RepetitionDuration (New-TimeSpan -Days 9999)

Register-ScheduledTask `
    -TaskName    "EconomicScript-Poll" `
    -Action      $ActionPoll `
    -Trigger     $PollTrigger `
    -Settings    $Settings `
    -Description "Revisa Gmail cada $PollMinutes min y envia alerta instantanea." `
    -Force | Out-Null
Write-Host "  OK  EconomicScript-Poll (cada $PollMinutes min)" -ForegroundColor Green

# ── Evening 19:00 — resumen del día + acumulado del mes (tier 1) ───────────────
$ActionEvening = New-ScheduledTaskAction `
    -Execute          "cmd.exe" `
    -Argument         "/c `"$DailyCmd`" --today" `
    -WorkingDirectory $ScriptDir

Register-ScheduledTask `
    -TaskName    "EconomicScript-Evening" `
    -Action      $ActionEvening `
    -Trigger     (New-ScheduledTaskTrigger -Daily -At "19:00") `
    -Settings    $Settings `
    -Description "19:00: ingesta + resumen tier-1 del dia y acumulado del mes (ciclo dia 27)." `
    -Force | Out-Null
Write-Host "  OK  EconomicScript-Evening (19:00 --today)" -ForegroundColor Green

# ── Daily matutino: se deshabilita (un solo correo al día a las 19:00) ─────────
$ActionDaily = New-ScheduledTaskAction `
    -Execute          "cmd.exe" `
    -Argument         "/c `"$DailyCmd`" --yesterday" `
    -WorkingDirectory $ScriptDir

Register-ScheduledTask `
    -TaskName    "EconomicScript-Daily" `
    -Action      $ActionDaily `
    -Trigger     (New-ScheduledTaskTrigger -Daily -At "07:00") `
    -Settings    $Settings `
    -Description "Opcional: resumen de ayer a las 07:00. Deshabilitado por defecto." `
    -Force | Out-Null
Disable-ScheduledTask -TaskName "EconomicScript-Daily" -ErrorAction SilentlyContinue | Out-Null
Write-Host "  OK  EconomicScript-Daily (07:00) DESHABILITADA (solo 19:00 activo)" -ForegroundColor Yellow

Write-Host ""
Write-Host "Tareas activas:"
Get-ScheduledTask | Where-Object { $_.TaskName -like 'EconomicScript*' } |
    Select-Object TaskName, State | Format-Table -AutoSize

Write-Host "Comandos utiles:"
Write-Host "  Probar poll ahora  : Start-ScheduledTask -TaskName 'EconomicScript-Poll'"
Write-Host "  Probar reporte 19h : Start-ScheduledTask -TaskName 'EconomicScript-Evening'"
Write-Host "  Ver ultima ejecucion: Get-ScheduledTaskInfo -TaskName 'EconomicScript-Poll'"
Write-Host ""
Write-Host "Reportes diarios a las 19:00 -> SMTP_TO en .env"
