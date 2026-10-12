param(
    [string]$AndroidSdk = $env:ANDROID_HOME,
    [string]$SigningKey = $env:DCP_TERMINAL_SIGNING_KEY,
    [string]$DeliveryDirectory = $env:DCP_APK_DELIVERY_DIR
)
$ErrorActionPreference = 'Stop'
$androidProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$taskWorkspaceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..'))
if (-not $AndroidSdk) { $AndroidSdk = Join-Path $env:LOCALAPPDATA 'Android\Sdk' }
if (-not (Test-Path -LiteralPath (Join-Path $AndroidSdk 'platforms\android-35\android.jar'))) {
    throw 'Android SDK platform 35 is required.'
}
if (-not $SigningKey -or -not (Test-Path -LiteralPath $SigningKey)) {
    throw 'Set DCP_TERMINAL_SIGNING_KEY to the existing private signing key outside the repository.'
}
$SigningKey = [IO.Path]::GetFullPath($SigningKey)
if ($SigningKey.StartsWith($taskWorkspaceRoot.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The private signing key must remain outside the project workspace.'
}
$env:ANDROID_HOME = $AndroidSdk
$env:DCP_TERMINAL_SIGNING_KEY = $SigningKey
('sdk.dir=' + $AndroidSdk.Replace('\', '/')) | Set-Content -LiteralPath (Join-Path $androidProjectRoot 'local.properties') -Encoding utf8
Push-Location $androidProjectRoot
try {
    & '.\gradlew.bat' --no-daemon --max-workers=2 assembleDebug assembleDebugAndroidTest lintDebug
    if ($LASTEXITCODE -ne 0) { throw 'Android build or lint failed.' }
    New-Item -ItemType Directory -Path 'build\data-tests' -Force | Out-Null
    & javac -encoding UTF-8 -d 'build\data-tests' 'app\src\main\java\top\dcpstudios\calendarwidget\CalendarData.java' 'app\src\main\java\top\dcpstudios\calendarwidget\TimetableData.java' 'tests\CalendarDataTest.java' 'tests\TimetableDataTest.java'
    if ($LASTEXITCODE -ne 0) { throw 'Data-test compilation failed.' }
    & java -cp 'build\data-tests' CalendarDataTest
    if ($LASTEXITCODE -ne 0) { throw 'Calendar data checks failed.' }
    & java -cp 'build\data-tests' top.dcpstudios.calendarwidget.TimetableDataTest
    if ($LASTEXITCODE -ne 0) { throw 'Timetable data checks failed.' }
    New-Item -ItemType Directory -Path 'release' -Force | Out-Null
    $androidVersion = [Regex]::Match((Get-Content -LiteralPath 'app\build.gradle' -Raw), "versionName '([^']+)'").Groups[1].Value
    if (-not $androidVersion) { throw 'Android versionName could not be read for release naming.' }
    $androidReleaseName = 'DCP-Terminal-' + $androidVersion + '.apk'
    $androidReleasePath = Join-Path 'release' $androidReleaseName
    Copy-Item -LiteralPath 'app\build\outputs\apk\debug\app-debug.apk' -Destination $androidReleasePath -Force
    if ($DeliveryDirectory) {
        $androidDeliveryDirectory = [IO.Path]::GetFullPath($DeliveryDirectory)
        New-Item -ItemType Directory -Path $androidDeliveryDirectory -Force | Out-Null
        $androidDeliveryPath = Join-Path $androidDeliveryDirectory $androidReleaseName
        if (-not [IO.Path]::GetFullPath($androidReleasePath).Equals($androidDeliveryPath, [StringComparison]::OrdinalIgnoreCase)) {
            Copy-Item -LiteralPath $androidReleasePath -Destination $androidDeliveryPath -Force
        }
        if ((Get-FileHash -LiteralPath $androidReleasePath -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $androidDeliveryPath -Algorithm SHA256).Hash) { throw 'Additional release APK hash verification failed.' }
    }
    $androidReportDirectory = Join-Path $taskWorkspaceRoot 'doc\Android_DCP_Terminal'
    New-Item -ItemType Directory -Path $androidReportDirectory -Force | Out-Null
    Copy-Item -LiteralPath 'app\build\reports\lint-results-debug.html' -Destination (Join-Path $androidReportDirectory 'lint-results-debug.html') -Force
    $androidLintReport = Join-Path $androidReportDirectory 'lint-results-debug.html'
    $androidLintHtml = Get-Content -LiteralPath $androidLintReport -Raw
    foreach ($androidPrivatePath in @($taskWorkspaceRoot, $AndroidSdk, $env:USERPROFILE)) {
        if ($androidPrivatePath) {
            $androidLintHtml = $androidLintHtml.Replace($androidPrivatePath, '[local-path]').Replace($androidPrivatePath.Replace('\', '/'), '[local-path]')
        }
    }
    ('<!-- 生成日期：' + (Get-Date -Format 'yyyy-MM-dd') + '；文档概要：DCP Terminal Android lint 检查报告。 -->' + [Environment]::NewLine + $androidLintHtml) | Set-Content -LiteralPath $androidLintReport -Encoding utf8
} finally { Pop-Location }
