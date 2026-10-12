param([string]$Serial = 'emulator-5580', [string]$AndroidSdk = $env:ANDROID_HOME, [Alias('PublicWebView')][switch]$PublicNativeLogin)
$ErrorActionPreference = 'Stop'
if (-not $Serial.StartsWith('emulator-')) { throw 'These destructive cache fixtures must run only on an isolated emulator.' }
if (-not $AndroidSdk) { $AndroidSdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
$androidTestAdb = Join-Path $AndroidSdk 'platform-tools\adb.exe'
$androidProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
& $androidTestAdb -s $Serial install -r (Join-Path $androidProjectRoot 'app\build\outputs\apk\debug\app-debug.apk')
if ($LASTEXITCODE -ne 0) { throw 'App installation failed.' }
& $androidTestAdb -s $Serial install -r (Join-Path $androidProjectRoot 'app\build\outputs\apk\androidTest\debug\app-debug-androidTest.apk')
if ($LASTEXITCODE -ne 0) { throw 'Instrumentation installation failed.' }
$androidIntegrationOutput = & $androidTestAdb -s $Serial shell am instrument -w 'top.dcpstudios.calendarwidget.test/top.dcpstudios.calendarwidget.TerminalIntegrationInstrumentation'
$androidIntegrationOutput | Write-Output
if (-not ($androidIntegrationOutput -match 'PASS: native NetDisk tab')) { throw 'Native account isolation checks failed.' }
& $androidTestAdb -s $Serial shell appwidget grantbind --package top.dcpstudios.calendarwidget --user 0
$androidWidgetOutput = & $androidTestAdb -s $Serial shell am instrument -w -e suite widget 'top.dcpstudios.calendarwidget.test/top.dcpstudios.calendarwidget.TerminalIntegrationInstrumentation'
$androidWidgetOutput | Write-Output
if (-not ($androidWidgetOutput -match 'PASS: widget host')) { throw 'Widget collection checks failed.' }
if ($PublicNativeLogin) {
    $androidPublicOutput = & $androidTestAdb -s $Serial shell am instrument -w -e suite public 'top.dcpstudios.calendarwidget.test/top.dcpstudios.calendarwidget.TerminalIntegrationInstrumentation'
    $androidPublicOutput | Write-Output
    if (-not ($androidPublicOutput -match 'PASS: actual native')) { throw 'Native login UI check failed.' }
}
