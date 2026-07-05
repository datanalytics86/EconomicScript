<#
.SYNOPSIS
    Carga los secrets de .env a GitHub Actions automáticamente.

.REQUIRES
    GitHub CLI autenticado: gh auth login

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/setup_github_secrets.ps1
#>

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$EnvFile = Join-Path $ProjectDir ".env"

if (-not (Test-Path $EnvFile)) {
    Write-Error ".env no encontrado en $ProjectDir"
}

$gh = Get-Command gh -ErrorAction SilentlyContinue
if (-not $gh) {
    Write-Error "Instala GitHub CLI: winget install GitHub.cli"
}

Set-Location $ProjectDir
$repo = gh repo view --json nameWithOwner -q .nameWithOwner
Write-Host "Configurando secrets en: $repo"
Write-Host ""

$keys = @(
    "IMAP_USER",
    "OAUTH_CLIENT_ID",
    "OAUTH_CLIENT_SECRET",
    "OAUTH_REFRESH_TOKEN",
    "SMTP_TO",
    "SMTP_PASSWORD",
    "SMTP_USER"
)

foreach ($line in Get-Content $EnvFile) {
    if ($line -match '^\s*([^#=]+)=(.*)$') {
        $key = $matches[1].Trim()
        $val = $matches[2].Trim()
        if ($key -in $keys -and $val) {
            Write-Host "  → $key"
            $val | gh secret set $key --repo $repo
        }
    }
}

Write-Host ""
Write-Host "OK  Secrets configurados en GitHub." -ForegroundColor Green
Write-Host "Siguiente paso: git push y verificar Actions → Scheduled Alerts"