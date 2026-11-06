#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== WIKA APK Release — app-delivery v1 ==="
echo "Genera un APK autonomo: el bundle JS va embebido, no necesita Metro."

if ! command -v java >/dev/null 2>&1; then
  echo "ERROR: Java no encontrado. Instala JDK 17."
  exit 1
fi

echo ""
echo "Java: $(java -version 2>&1 | head -n1)"
if java -version 2>&1 | grep -qE 'version "(21|22|23|24|25|26)\.'; then
  echo "WARNING: WIKA requiere JDK 17. Apunta JAVA_HOME a un JDK 17 si Gradle falla."
fi

echo ""
echo "[1/4] prebuild android"
node scripts/patch-expo-camera.js
npx expo prebuild --platform android
node scripts/post-prebuild.js

echo ""
echo "[2/4] Android SDK"
LOCAL_PROPS="$ROOT/android/local.properties"
SDK_DIR="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"

if [[ -f "$LOCAL_PROPS" ]]; then
  echo "Usando android/local.properties existente"
elif [[ -n "$SDK_DIR" && -d "$SDK_DIR" ]]; then
  echo "sdk.dir=$SDK_DIR" > "$LOCAL_PROPS"
  echo "Escrito android/local.properties desde ANDROID_HOME"
else
  echo "ERROR: SDK de Android no configurado."
  echo "Exporta ANDROID_HOME o copia scripts/local.properties.example a android/local.properties"
  exit 1
fi

echo ""
echo "[3/4] gradle assembleRelease"
cd android
./gradlew assembleRelease
cd ..

echo ""
echo "[4/4] Listo"
echo "APK: android/app/build/outputs/apk/release/app-release.apk"
echo "Instalar: adb install -r android/app/build/outputs/apk/release/app-release.apk"
