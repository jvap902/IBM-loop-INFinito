# start-backend.ps1
# Carrega o .env e sobe o servidor FastAPI.
# Uso: .\start-backend.ps1

$envFile = Join-Path $PSScriptRoot ".env"

if (-not (Test-Path $envFile)) {
    Write-Error ".env nao encontrado. Copie .env.example para .env e preencha os valores."
    exit 1
}

Write-Host "Carregando variaveis de $envFile ..." -ForegroundColor Cyan

Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    # Ignora linhas vazias e comentarios
    if ($line -and -not $line.StartsWith("#")) {
        $idx = $line.IndexOf("=")
        if ($idx -gt 0) {
            $key   = $line.Substring(0, $idx).Trim()
            $value = $line.Substring($idx + 1).Trim()
            # Remove aspas se presentes
            $value = $value.Trim('"').Trim("'")
            # Usa $env: para garantir heranca por subprocessos
            Set-Item -Path "Env:$key" -Value $value
        }
    }
}

# Confirma variaveis criticas
Write-Host ""
Write-Host "Variaveis carregadas:" -ForegroundColor Green
Write-Host "  LLM_PROVIDER       = $env:LLM_PROVIDER"
Write-Host "  TOOL_API_KEY       = $(if ($env:TOOL_API_KEY) { '(definida)' } else { 'AUSENTE' })"
Write-Host "  WATSONX_API_KEY    = $(if ($env:WATSONX_API_KEY) { '(definida)' } else { 'n/a' })"
Write-Host "  WATSONX_PROJECT_ID = $(if ($env:WATSONX_PROJECT_ID) { '(definida)' } else { 'n/a' })"
Write-Host "  GEMINI_API_KEY     = $(if ($env:GEMINI_API_KEY) { '(definida)' } else { 'n/a' })"
Write-Host "  GEMINI_MODEL_ID    = $(if ($env:GEMINI_MODEL_ID) { $env:GEMINI_MODEL_ID } else { 'gemini-1.5-flash (default)' })"
Write-Host "  GOLD_PARQUET_PATH  = $env:GOLD_PARQUET_PATH"
Write-Host "  CORS_ORIGINS       = $env:CORS_ORIGINS"
Write-Host ""

# Valida que Python ve as variaveis antes de subir o servidor
$check = python -c "import os; print(os.getenv('LLM_PROVIDER','NAO_DEFINIDO'))" 2>&1
Write-Host "Python ve LLM_PROVIDER = $check" -ForegroundColor $(if ($check -ne "NAO_DEFINIDO") { "Green" } else { "Red" })

if ($check -eq "NAO_DEFINIDO") {
    Write-Warning "Python nao esta vendo as variaveis. Verifique o .env."
    exit 1
}

Write-Host ""
Write-Host "Subindo FastAPI na porta 8000..." -ForegroundColor Cyan
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
