set -eu
cd "$(dirname "$0")"
: "${ANDROID_HOME:?Set ANDROID_HOME to the local Android SDK}"
: "${DCP_TERMINAL_SIGNING_KEY:?Set DCP_TERMINAL_SIGNING_KEY to an external private signing key}"
project_root="$(pwd -P)"
workspace_root="$(cd ../.. && pwd -P)"
signing_key="$(realpath "$DCP_TERMINAL_SIGNING_KEY")"
case "$signing_key" in "$workspace_root"/*) echo 'Keep the private signing key outside the repository.' >&2; exit 1;; esac
test -f "$signing_key"
export DCP_TERMINAL_SIGNING_KEY="$signing_key"
sh ./gradlew --no-daemon --max-workers=2 assembleDebug assembleDebugAndroidTest lintDebug
mkdir -p build/data-tests
javac -encoding UTF-8 -d build/data-tests app/src/main/java/top/dcpstudios/calendarwidget/CalendarData.java app/src/main/java/top/dcpstudios/calendarwidget/TimetableData.java tests/CalendarDataTest.java tests/TimetableDataTest.java
java -cp build/data-tests CalendarDataTest
java -cp build/data-tests top.dcpstudios.calendarwidget.TimetableDataTest
mkdir -p release
version="$(sed -n "s/.*versionName '\([^']*\)'.*/\1/p" app/build.gradle)"
test -n "$version"
release_name="DCP-Terminal-$version.apk"
cp app/build/outputs/apk/debug/app-debug.apk "release/$release_name"
if [ -n "${DCP_APK_DELIVERY_DIR:-}" ]; then
  mkdir -p "$DCP_APK_DELIVERY_DIR"
  delivery_root="$(cd "$DCP_APK_DELIVERY_DIR" && pwd -P)"
  if [ "$delivery_root" != "$project_root/release" ]; then
    cp "release/$release_name" "$delivery_root/$release_name"
  fi
  local_hash="$(sha256sum "release/$release_name" | cut -d ' ' -f 1)"
  delivery_hash="$(sha256sum "$delivery_root/$release_name" | cut -d ' ' -f 1)"
  test "$local_hash" = "$delivery_hash"
fi
