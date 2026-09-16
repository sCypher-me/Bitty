param(
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)')]
  [string]$LanAddress
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$mobileRoot = Join-Path $projectRoot "apps\mobile"
$androidRoot = Join-Path $mobileRoot "android"
$outputRoot = Join-Path $projectRoot "outputs"
$cap = Join-Path $mobileRoot "node_modules\.bin\cap.cmd"
$gradle = Join-Path $androidRoot "gradlew.bat"
$jdkRoot = Join-Path $env:USERPROFILE ".jdks"
$jdk21 = Get-ChildItem -LiteralPath $jdkRoot -Directory -Filter "jbr-21*" -ErrorAction SilentlyContinue |
  Sort-Object Name -Descending |
  Select-Object -First 1
$compatibleJdk = if ($jdk21) { $jdk21.FullName } else { "C:\Program Files\Android\Android Studio\jbr" }
$androidSdk = Join-Path $env:LOCALAPPDATA "Android\Sdk"

if (-not (Test-Path -LiteralPath $cap)) { throw "Dependencias mobile ausentes. Execute pnpm install em apps/mobile." }
if (-not (Test-Path -LiteralPath $gradle)) { throw "Gradle wrapper Android ausente." }
if (-not (Test-Path -LiteralPath $compatibleJdk)) { throw "JDK compativel nao encontrado." }
if (-not (Test-Path -LiteralPath $androidSdk)) { throw "Android SDK nao encontrado em $androidSdk." }

$env:BITTY_APP_URL = "http://${LanAddress}:3000"
$env:BITTY_ALLOW_HTTP_LAN = "true"
$env:JAVA_HOME = $compatibleJdk
$env:ANDROID_HOME = $androidSdk
$env:ANDROID_USER_HOME = Join-Path $env:USERPROFILE ".android"
$env:GRADLE_USER_HOME = Join-Path $env:USERPROFILE ".gradle"

Push-Location $mobileRoot
try {
  & $cap sync android
  if ($LASTEXITCODE -ne 0) { throw "Capacitor sync falhou." }
} finally {
  Pop-Location
}

Push-Location $androidRoot
try {
  & $gradle testDebugUnitTest lintDebug assembleDebug --no-daemon
  if ($LASTEXITCODE -ne 0) { throw "Build Android falhou." }
} finally {
  Pop-Location
}

New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
$sourceApk = Join-Path $androidRoot "app\build\outputs\apk\debug\app-debug.apk"
$targetApk = Join-Path $outputRoot "Bitty-LAN-debug.apk"
Copy-Item -LiteralPath $sourceApk -Destination $targetApk -Force
$hash = Get-FileHash -LiteralPath $targetApk -Algorithm SHA256
Write-Host "APK criado: $targetApk"
Write-Host "Servidor configurado: $env:BITTY_APP_URL"
Write-Host "SHA256: $($hash.Hash)"
