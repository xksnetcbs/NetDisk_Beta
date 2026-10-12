set -eu
: "${ANDROID_HOME:?Set ANDROID_HOME to the local Android SDK}"
"$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" "emulator" "system-images;android-35;default;x86_64"
