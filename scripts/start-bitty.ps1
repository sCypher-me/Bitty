param(
  [string]$LanAddress,
  [int]$ApiPort = 8010
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$apiRoot = Join-Path $projectRoot "apps\api"
$webRoot = Join-Path $projectRoot "apps\web"
$logRoot = Join-Path $projectRoot ".bitty-logs"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

if (-not $LanAddress) {
  try {
    $LanAddress = Get-NetIPConfiguration |
      Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } |
      ForEach-Object { $_.IPv4Address.IPAddress } |
      Where-Object { $_ -match '^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)' } |
      Select-Object -First 1
  } catch {
    Write-Warning "Nao foi possivel detectar o IP local automaticamente. Use -LanAddress 192.168.x.x."
  }
}

$env:API_INTERNAL_URL = "http://127.0.0.1:${ApiPort}"
if ($LanAddress) { $env:BITTY_LAN_HOST = $LanAddress }

if (-not (Get-NetTCPConnection -LocalPort $ApiPort -State Listen -ErrorAction SilentlyContinue)) {
  $python = Join-Path $apiRoot ".venv\Scripts\python.exe"
  Start-Process -FilePath $python -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port",$ApiPort -WorkingDirectory $apiRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot "api.log") -RedirectStandardError (Join-Path $logRoot "api-error.log")
}
if (-not (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue)) {
  $next = Join-Path $webRoot "node_modules\.bin\next.cmd"
  Start-Process -FilePath $next -ArgumentList "dev","--hostname","0.0.0.0" -WorkingDirectory $webRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot "web.log") -RedirectStandardError (Join-Path $logRoot "web-error.log")
}

$deadline = (Get-Date).AddSeconds(30)
do {
  $apiReady = $false
  $webReady = $false
  try { $apiReady = (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:${ApiPort}/ready" -TimeoutSec 2).StatusCode -eq 200 } catch {}
  try { $webReady = (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:3000/" -TimeoutSec 2).StatusCode -eq 200 } catch {}
  if (-not ($apiReady -and $webReady)) { Start-Sleep -Milliseconds 500 }
} while ((Get-Date) -lt $deadline -and -not ($apiReady -and $webReady))

if (-not $apiReady) { throw "API nao ficou pronta na porta $ApiPort. Consulte .bitty-logs\api-error.log." }
if (-not $webReady) { throw "Frontend nao ficou pronto na porta 3000. Consulte .bitty-logs\web-error.log." }

Write-Host "Bitty iniciado no notebook: http://127.0.0.1:3000"
if ($LanAddress) { Write-Host "Na rede local: http://${LanAddress}:3000" }
Write-Host "Logs: $logRoot"
