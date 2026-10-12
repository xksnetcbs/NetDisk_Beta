param(
    [Parameter(Mandatory = $true)][string]$FixturePath,
    [string]$Serial = 'emulator-5580',
    [string]$AndroidSdk = $env:ANDROID_HOME,
    [switch]$Upgrade
)
$ErrorActionPreference = 'Stop'
if (-not $Serial.StartsWith('emulator-')) { throw 'Temporary real-server credentials may only be used in the isolated emulator.' }
$FixturePath = [IO.Path]::GetFullPath($FixturePath)
if (-not (Test-Path -LiteralPath $FixturePath)) { throw 'Private temporary account fixture was not found.' }
$androidProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskWorkspaceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..'))
if ($FixturePath.StartsWith($taskWorkspaceRoot.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Temporary account credentials must remain outside the workspace.'
}
if (-not $AndroidSdk) { $AndroidSdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
$androidTestAdb = Join-Path $AndroidSdk 'platform-tools\adb.exe'
if ($Upgrade) {
    & $androidTestAdb -s $Serial install -r -d (Join-Path $androidProjectRoot 'release\DCP-Terminal-1.5.0.apk')
} else {
    & $androidTestAdb -s $Serial install -r (Join-Path $androidProjectRoot 'app\build\outputs\apk\debug\app-debug.apk')
}
if ($LASTEXITCODE -ne 0) { throw 'App installation failed.' }
& $androidTestAdb -s $Serial install -r (Join-Path $androidProjectRoot 'app\build\outputs\apk\androidTest\debug\app-debug-androidTest.apk')
if ($LASTEXITCODE -ne 0) { throw 'Instrumentation installation failed.' }
& $androidTestAdb -s $Serial shell run-as top.dcpstudios.calendarwidget mkdir -p files
$androidFixtureInstaller = @'
import pathlib,subprocess,sys
data=pathlib.Path(sys.argv[1]).read_bytes()
result=subprocess.run([sys.argv[3],'-s',sys.argv[2],'shell','-T','run-as','top.dcpstudios.calendarwidget','tee','files/netdisk-merge-qa.json'],input=data,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
if result.returncode: raise SystemExit('Private fixture installation failed')
'@
try {
    & python -c $androidFixtureInstaller $FixturePath $Serial $androidTestAdb
    if ($LASTEXITCODE -ne 0) { throw 'Private fixture installation failed.' }
    if ($Upgrade) {
        $androidSeedOutput = & $androidTestAdb -s $Serial shell am instrument -w -e suite upgrade-seed 'top.dcpstudios.calendarwidget.test/top.dcpstudios.calendarwidget.TerminalIntegrationInstrumentation'
        $androidSeedOutput | Write-Output
        if (-not ($androidSeedOutput -match 'PASS: real upgrade-seed')) { throw 'Installed-version migration seed failed.' }
        & $androidTestAdb -s $Serial install -r (Join-Path $androidProjectRoot 'app\build\outputs\apk\debug\app-debug.apk')
        if ($LASTEXITCODE -ne 0) { throw 'APK upgrade installation failed.' }
        $androidUpgradeOutput = & $androidTestAdb -s $Serial shell am instrument -w -e suite upgrade-verify 'top.dcpstudios.calendarwidget.test/top.dcpstudios.calendarwidget.TerminalIntegrationInstrumentation'
        $androidUpgradeOutput | Write-Output
        if (-not ($androidUpgradeOutput -match 'PASS: real upgrade-verify')) { throw 'Installed-version migration acceptance failed.' }
    } else {
        $androidRemoteOutput = & $androidTestAdb -s $Serial shell am instrument -w -e suite remote 'top.dcpstudios.calendarwidget.test/top.dcpstudios.calendarwidget.TerminalIntegrationInstrumentation'
        $androidRemoteOutput | Write-Output
        if (-not ($androidRemoteOutput -match 'PASS: real HTTPS native login')) { throw 'Real-server acceptance failed; credentials were not printed.' }
    }
} finally {
    & $androidTestAdb -s $Serial shell run-as top.dcpstudios.calendarwidget rm -f files/netdisk-merge-qa.json
}
