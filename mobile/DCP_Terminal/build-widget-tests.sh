set -eu
cd "$(dirname "$0")"
sh ./gradlew --no-daemon --max-workers=2 assembleDebug assembleDebugAndroidTest
