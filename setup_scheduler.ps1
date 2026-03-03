<#
.SYNOPSIS
    Registra la tarea diaria de EconomicScript en el Programador de tareas de Windows.

.DESCRIPTION
    Crea la tarea "EconomicScript-Daily" que ejecuta run_daily.py todos los días
    a las 06:55 hrs. El reporte llega por email a las ~07:00 con las transacciones
    del día anterior y el acumulado del ciclo de gasto.

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
$TaskName   = "EconomicScript-Daily"
$RunHour    = "06:55"

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
Write-Host "Configurando tarea programada '$TaskName'..."
Write-Host "  Python    : $PythonExe"
Write-Host "  Script    : $RunScript"
Write-Host "  Directorio: $ScriptDir"
Write-Host "  Horario   : Diario a las $RunHour hrs"
Write-Host ""

$Action = New-ScheduledTaskAction `
    -Execute    $PythonExe `
    -Argument   "`"$RunScript`"" `
    -WorkingDirectory $ScriptDir

$Trigger = New-ScheduledTaskTrigger -Daily -At $RunHour

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit    (New-TimeSpan -Hours 1) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances     IgnoreNew

Register-ScheduledTask `
    -TaskName    $TaskName `
    -Action      $Action `
    -Trigger     $Trigger `
    -Settings    $Settings `
    -Description "Ingesta Gmail, auto-categoriza y envia resumen diario de finanzas personales." `
    -Force | Out-Null

Write-Host "OK  Tarea '$TaskName' registrada exitosamente." -ForegroundColor Green
Write-Host ""
Write-Host "Comandos utiles:"
Write-Host "  Ejecutar ahora    : Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Ver estado        : Get-ScheduledTask  -TaskName '$TaskName' | Select-Object TaskName, State"
Write-Host "  Eliminar tarea    : Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
Write-Host ""
Write-Host "El reporte llegara a la direccion configurada en SMTP_TO del archivo .env"
