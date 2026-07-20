# Lanza el dashboard Streamlit de EconomicScript.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$py = $null
$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pyLauncher) {
    $py = (& py -3 -c "import sys; print(sys.executable)" 2>$null)
}
if (-not $py) {
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $py) {
    Write-Error "Python no encontrado"
    exit 1
}

& $py -m streamlit run app.py --server.headless true --server.port 8501
