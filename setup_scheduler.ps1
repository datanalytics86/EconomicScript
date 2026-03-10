<#
.SYNOPSIS
    Registra las tareas diarias de EconomicScript en el Programador de tareas de Windows.

.DESCRIPTION
    Crea dos tareas programadas:
    - "EconomicScript-Daily"  : 07:00 hrs, reporta las transacciones del día anterior (completo).
    - "EconomicScript-Evening": 20:00 hrs, reporta las transacciones del día actual hasta ese momento.

.NOTES
    - Ejecutar con privilegios de Administrador (clic derecho → "Ejecutar como administrador").
    - Python debe estar instalado y accesible como 'python' en el PATH.
    - Antes de ejecutar este script, configura tu archivo .env con SMTP_TO y las
      credenciales de Gmail (ver .env.example).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1
#>

$ErrorActionPreference = "Stop"

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunScript  = Join-Path $ScriptDir "run_daily.py"
$TaskName        = "EconomicScript-Daily"
$TaskNameEvening = "EconomicScript-Evening"
$RunHour         = "07:00"
$RunHourEvening  = "20:00"

# ── Verificaciones previas ─────────────────────────────────────────────────────
$PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $PythonExe) {
    Write-Error "Python no encontrado en PATH. Instala Python 3.10+ y vuelve a ejecutar."
    exit 1
}

if (-not (Test-Path $RunScript)) {
    Write-Error "No se encontró run_daily.py en: $RunScript"
    exit 1
}

$EnvFile = Join-Path $ScriptDir ".env"
if (-not (Test-Path $EnvFile)) {
    Write-Warning ".env no encontrado. Copia .env.example a .env y configura tus credenciales antes de que la tarea se ejecute."
}

# ── Registro de la tarea ───────────────────────────────────────────────────────
Write-Host ""
Write-Host "Configurando tareas programadas de EconomicScript..."
Write-Host "  Python    : $PythonExe"
Write-Host "  Script    : $RunScript"
Write-Host "  Directorio: $ScriptDir"
Write-Host ""

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit    (New-TimeSpan -Hours 1) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances     IgnoreNew

# ── Tarea matutina (07:00) — reporte del día anterior ─────────────────────────
Write-Host "  Registrando '$TaskName' a las $RunHour hrs (reporte de ayer)..."

$Action = New-ScheduledTaskAction `
    -Execute          $PythonExe `
    -Argument         "`"$RunScript`"" `
    -WorkingDirectory $ScriptDir

$Trigger = New-ScheduledTaskTrigger -Daily -At $RunHour

Register-ScheduledTask `
    -TaskName    $TaskName `
    -Action      $Action `
    -Trigger     $Trigger `
    -Settings    $Settings `
    -Description "Ingesta Gmail, auto-categoriza y envia resumen del dia anterior." `
    -Force | Out-Null

Write-Host "  OK  '$TaskName' registrada." -ForegroundColor Green

# ── Tarea vespertina (20:00) — resumen parcial del día actual ─────────────────
Write-Host "  Registrando '$TaskNameEvening' a las $RunHourEvening hrs (resumen de hoy)..."

$ActionEvening = New-ScheduledTaskAction `
    -Execute          $PythonExe `
    -Argument         "`"$RunScript`" --today" `
    -WorkingDirectory $ScriptDir

$TriggerEvening = New-ScheduledTaskTrigger -Daily -At $RunHourEvening

Register-ScheduledTask `
    -TaskName    $TaskNameEvening `
    -Action      $ActionEvening `
    -Trigger     $TriggerEvening `
    -Settings    $Settings `
    -Description "Envia resumen parcial de gastos del dia actual a las 20:00 hrs." `
    -Force | Out-Null

Write-Host "  OK  '$TaskNameEvening' registrada." -ForegroundColor Green

Write-Host ""
Write-Host "Comandos utiles:"
Write-Host "  Ver tareas        : Get-ScheduledTask | Where-Object { `$_.TaskName -like 'EconomicScript*' }"
Write-Host "  Ejecutar manana   : Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Ejecutar tarde    : Start-ScheduledTask -TaskName '$TaskNameEvening'"
Write-Host "  Eliminar ambas    : 'EconomicScript-Daily','EconomicScript-Evening' | ForEach-Object { Unregister-ScheduledTask -TaskName `$_ -Confirm:`$false }"
Write-Host ""
Write-Host "Los reportes llegaran a la direccion configurada en SMTP_TO del archivo .env"
