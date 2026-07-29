# Wrapper confiable para tareas programadas de EconomicScript.
# Resuelve Python real (evita el stub de Microsoft Store) y fija el directorio.

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

function Resolve-PythonExe {
    # 1) py launcher (más confiable en Windows)
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $versioned = & py -3 -c "import sys; print(sys.executable)" 2>$null
        if ($versioned -and (Test-Path $versioned)) { return $versioned.Trim() }
    }

    # 2) Python instalado via pythoncore (no WindowsApps)
    $candidates = @(
        "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\python.exe",
        "$env:LOCALAPPDATA\Python\pythoncore-3.13-64\python.exe",
        "$env:LOCALAPPDATA\Python\pythoncore-3.12-64\python.exe",
        "$env:LOCALAPPDATA\Python\bin\python.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }

    # 3) Fallback: python en PATH (puede ser stub)
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    throw "Python no encontrado. Instala Python 3.10+ desde python.org"
}

$PythonExe = Resolve-PythonExe
$Script = $args[0]

# IMPORTANTE: no usar $args[1..($args.Length-1)] cuando Length==1.
# En PowerShell, el rango reverso [1..0] devuelve el elemento 0 otra vez
# (p.ej. "run_daily.py"), y Python falla con exit code 2.
if ($args.Count -gt 1) {
    $ScriptArgs = $args[1..($args.Count - 1)]
} else {
    $ScriptArgs = @()
}

if (-not $Script) {
    Write-Error "Uso: run_task.ps1 <script.py> [argumentos...]"
    exit 1
}

$ScriptPath = Join-Path $ScriptDir $Script
if (-not (Test-Path $ScriptPath)) {
    Write-Error "Script no encontrado: $ScriptPath"
    exit 1
}

& $PythonExe $ScriptPath @ScriptArgs
exit $LASTEXITCODE
