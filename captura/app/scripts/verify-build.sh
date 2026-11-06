#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== WIKA Build Verification — app-delivery v1 ==="

echo ""
echo "[1/7] Toolchain"

if ! command -v java >/dev/null 2>&1; then
  echo "ERROR: Java not found. Install JDK 17 (WIKA standard)."
  exit 1
fi

echo "Java: $(java -version 2>&1 | head -n1)"
if java -version 2>&1 | grep -qE 'version "(21|22|23|24|25|26)\.'; then
  echo "WARNING: WIKA requires JDK 17 for Gradle. Point JAVA_HOME at a JDK 17 install if Gradle fails."
fi

echo ""
echo "[2/7] Smoke (engine)"
npm run smoke

echo ""
echo "[3/7] TypeScript"
npx tsc --noEmit

echo ""
echo "[4/7] Bundle JS"
npx expo export --platform android

echo ""
echo "[5/7] prebuild android"
npx expo prebuild --platform android
node scripts/post-prebuild.js

echo ""
echo "[6/7] Android SDK"
LOCAL_PROPS="$ROOT/android/local.properties"
SDK_DIR="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"

if [[ -f "$LOCAL_PROPS" ]]; then
  echo "Using existing android/local.properties"
elif [[ -n "$SDK_DIR" && -d "$SDK_DIR" ]]; then
  echo "sdk.dir=$SDK_DIR" > "$LOCAL_PROPS"
  echo "Wrote android/local.properties from ANDROID_HOME"
else
  echo "ERROR: Android SDK not configured."
  echo "Export ANDROID_HOME, or copy scripts/local.properties.example to android/local.properties"
  exit 1
fi

echo ""
echo "[7/7] gradle assembleRelease"
cd android
./gradlew assembleRelease
cd ..

echo ""
echo "All gates passed"
echo "APK: android/app/build/outputs/apk/release/app-release.apk"
