$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$apiRoot = Join-Path $projectRoot "apps\api"
$webRoot = Join-Path $projectRoot "apps\web"
$logRoot = Join-Path $projectRoot ".bitty-logs"
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

if (-not (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue)) {
  $python = Join-Path $apiRoot ".venv\Scripts\python.exe"
  Start-Process -FilePath $python -ArgumentList "-m","uvicorn","app.main:app","--host","0.0.0.0","--port","8000" -WorkingDirectory $apiRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot "api.log") -RedirectStandardError (Join-Path $logRoot "api-error.log")
}
if (-not (Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue)) {
  $next = Join-Path $webRoot "node_modules\.bin\next.cmd"
  Start-Process -FilePath $next -ArgumentList "dev","--hostname","0.0.0.0" -WorkingDirectory $webRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot "web.log") -RedirectStandardError (Join-Path $logRoot "web-error.log")
}

$lanAddress = $null
try {
  $lanAddress = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop | Where-Object {$_.IPAddress -match '^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)'} | Select-Object -First 1 -ExpandProperty IPAddress
} catch {
  Write-Host "Nao foi possivel detectar o IP local automaticamente."
}
Write-Host "Bitty iniciado no notebook: http://127.0.0.1:3000"
if ($lanAddress) { Write-Host "Na rede local: http://${lanAddress}:3000" }
Write-Host "Logs: $logRoot"
