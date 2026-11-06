@echo off
setlocal
cd /d "%~dp0\.."
echo === WIKA APK Release — app-delivery v1 ===
call npx expo prebuild --platform android
if errorlevel 1 exit /b 1
call node scripts\post-prebuild.js
if not exist android\local.properties (
  if defined ANDROID_HOME (
    echo sdk.dir=%ANDROID_HOME:\=\\%> android\local.properties
  ) else (
    echo ERROR: Android SDK not configured.
    exit /b 1
  )
)
cd android
call gradlew.bat assembleRelease
if errorlevel 1 exit /b 1
echo APK: android\app\build\outputs\apk\release\app-release.apk
