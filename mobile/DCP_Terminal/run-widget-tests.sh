set -eu
cd "$(dirname "$0")"
: "${ANDROID_HOME:?Set ANDROID_HOME to the local Android SDK}"
SERIAL="${1:-emulator-5580}"
case "$SERIAL" in emulator-*) ;; *) echo 'Use an isolated emulator for destructive test fixtures.' >&2; exit 1;; esac
ADB="$ANDROID_HOME/platform-tools/adb"
"$ADB" -s "$SERIAL" install -r app/build/outputs/apk/debug/app-debug.apk
"$ADB" -s "$SERIAL" install -r app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
"$ADB" -s "$SERIAL" shell appwidget grantbind --package top.dcpstudios.calendarwidget --user 0
"$ADB" -s "$SERIAL" shell am instrument -w top.dcpstudios.calendarwidget.test/top.dcpstudios.calendarwidget.TerminalIntegrationInstrumentation
"$ADB" -s "$SERIAL" shell am instrument -w -e suite widget top.dcpstudios.calendarwidget.test/top.dcpstudios.calendarwidget.TerminalIntegrationInstrumentation
