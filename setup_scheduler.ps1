<#
.SYNOPSIS
    Registra las tareas automáticas de EconomicScript en el Programador de Windows.

.DESCRIPTION
    Crea tres tareas:
    - EconomicScript-Poll    : cada 10 min, revisa Gmail y alerta al instante
    - EconomicScript-Daily   : 07:00, reporte completo del día anterior
    - EconomicScript-Evening : 20:00, resumen parcial del día actual

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

$Tasks = @(
    @{
        Name        = "EconomicScript-Poll"
        Arguments   = "run_poll.py"
        Description = "Revisa Gmail cada 10 min y envia alerta instantanea por transaccion nueva."
        Schedule    = "Poll"
    },
    @{
        Name        = "EconomicScript-Daily"
        Arguments   = "run_daily.py"
        Description = "Ingesta Gmail, auto-categoriza y envia resumen del dia anterior."
        Schedule    = "Daily07"
    },
    @{
        Name        = "EconomicScript-Evening"
        Arguments   = "run_daily.py --today"
        Description = "Envia resumen parcial de gastos del dia actual a las 20:00."
        Schedule    = "Daily20"
    }
)

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

$PollCmd   = Join-Path $ScriptDir "poll.cmd"
$DailyCmd  = Join-Path $ScriptDir "daily.cmd"

foreach ($task in $Tasks) {
    if ($task.Schedule -eq "Poll") {
        $tr = "`"$PollCmd`""
        schtasks.exe /Create /TN $task.Name /TR $tr /SC MINUTE /MO $PollMinutes /F | Out-Null
        Write-Host "  OK  $($task.Name) (cada $PollMinutes min)" -ForegroundColor Green
        continue
    }

    $cmdArgs = if ($task.Schedule -eq "Daily20") { "`"$DailyCmd`" --today" } else { "`"$DailyCmd`"" }

    $Action = New-ScheduledTaskAction `
        -Execute          "cmd.exe" `
        -Argument         "/c $cmdArgs" `
        -WorkingDirectory $ScriptDir

    $Trigger = if ($task.Schedule -eq "Daily07") {
        New-ScheduledTaskTrigger -Daily -At "07:00"
    } else {
        New-ScheduledTaskTrigger -Daily -At "20:00"
    }

    Register-ScheduledTask `
        -TaskName    $task.Name `
        -Action      $Action `
        -Trigger     $Trigger `
        -Settings    $Settings `
        -Description $task.Description `
        -Force | Out-Null

    Write-Host "  OK  $($task.Name)" -ForegroundColor Green
}

# Eliminar tarea antigua con ruta incorrecta si existe
$oldTask = Get-ScheduledTask -TaskName "EconomicScript-Daily" -ErrorAction SilentlyContinue
if ($oldTask) {
    $oldAction = $oldTask.Actions[0]
    if ($oldAction.WorkingDirectory -and $oldAction.WorkingDirectory -notlike "*OneDrive*") {
        Write-Host "  Tarea antigua actualizada con nueva ruta." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Tareas activas:"
Get-ScheduledTask | Where-Object { $_.TaskName -like 'EconomicScript*' } |
    Select-Object TaskName, State | Format-Table -AutoSize

Write-Host "Comandos utiles:"
Write-Host "  Probar poll ahora  : Start-ScheduledTask -TaskName 'EconomicScript-Poll'"
Write-Host "  Probar reporte     : Start-ScheduledTask -TaskName 'EconomicScript-Daily'"
Write-Host "  Ver ultima ejecucion: Get-ScheduledTaskInfo -TaskName 'EconomicScript-Poll'"
Write-Host ""
Write-Host "Alertas instantaneas + reportes diarios → SMTP_TO en .env"