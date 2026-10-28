# start-frontend.ps1
# Sobe o servidor de desenvolvimento do frontend (Vite na porta 5173).
# Uso: .\start-frontend.ps1

$frontendDir = Join-Path $PSScriptRoot "frontend"

if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Write-Host "node_modules nao encontrado. Rodando npm install..." -ForegroundColor Yellow
    Push-Location $frontendDir
    npm install
    Pop-Location
}

Write-Host "Subindo Vite na porta 5173..." -ForegroundColor Cyan
Write-Host "UI disponivel em: http://localhost:5173" -ForegroundColor Green
Write-Host ""

Push-Location $frontendDir
npm run dev
Pop-Location
