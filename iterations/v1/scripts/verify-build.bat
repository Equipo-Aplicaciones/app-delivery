@echo off
setlocal
cd /d "%~dp0\.."

echo === WIKA Build Verification — app-delivery v1 ===

echo.
echo [1/6] Smoke
call npm run smoke
if errorlevel 1 exit /b 1

echo.
echo [2/6] TypeScript
call npx tsc --noEmit
if errorlevel 1 exit /b 1

echo.
echo [3/6] Bundle JS
call npx expo export --platform android
if errorlevel 1 exit /b 1

echo.
echo [4/6] prebuild android
call npx expo prebuild --platform android
if errorlevel 1 exit /b 1
call node scripts\post-prebuild.js

echo.
echo [5/6] Android SDK
if not exist android\local.properties (
  if defined ANDROID_HOME (
    echo sdk.dir=%ANDROID_HOME:\=\\%> android\local.properties
  ) else (
    echo ERROR: Android SDK not configured.
    exit /b 1
  )
)

echo.
echo [6/6] gradle assembleRelease
cd android
call gradlew.bat assembleRelease
if errorlevel 1 exit /b 1
cd ..

echo.
echo All gates passed
echo APK: android\app\build\outputs\apk\release\app-release.apk
