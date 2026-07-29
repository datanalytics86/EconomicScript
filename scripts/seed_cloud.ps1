<#
.SYNOPSIS
    Sube finance.db local a GitHub Actions cache para la nube.

.DESCRIPTION
    Requiere GitHub CLI (gh) autenticado: gh auth login
    Ejecutar UNA VEZ para migrar tu historial de 1800+ transacciones a la nube.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/seed_cloud.ps1
#>

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$DbPath = Join-Path $ProjectDir "finance.db"

if (-not (Test-Path $DbPath)) {
    Write-Error "No se encontró finance.db en: $DbPath"
}

$gh = Get-Command gh -ErrorAction SilentlyContinue
if (-not $gh) {
    Write-Error "Instala GitHub CLI: winget install GitHub.cli — luego: gh auth login"
}

$repo = gh repo view --json nameWithOwner -q .nameWithOwner 2>$null
if (-not $repo) {
    Set-Location $ProjectDir
    $repo = gh repo view --json nameWithOwner -q .nameWithOwner
}

$sizeKb = [math]::Round((Get-Item $DbPath).Length / 1024, 1)
Write-Host "Repositorio: $repo"
Write-Host "BD local: $DbPath ($sizeKb KB)"
Write-Host ""
Write-Host "Dispara el workflow 'Seed Database' y luego sube la BD..."
Write-Host ""

# Crear release temporal con la BD para que el workflow la descargue
$tag = "db-seed-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
gh release create $tag $DbPath --repo $repo --title "DB Seed EconomicScript" --notes "Seed one-time finance.db para alertas en la nube. Puede eliminarse después."

Write-Host ""
Write-Host "OK  finance.db subido al release '$tag'" -ForegroundColor Green
Write-Host ""
Write-Host "Ahora en GitHub:"
Write-Host "  1. Ve a Actions → Scheduled Alerts → Run workflow (slot: afternoon)"
Write-Host "  2. Configura los SECRETS si aún no lo hiciste (ver .github/workflows/scheduled-alerts.yml)"
Write-Host "  3. Las alertas llegarán a las 7:00, 14:00 y 21:00 sin prender el PC"