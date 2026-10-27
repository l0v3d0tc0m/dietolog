@echo off
rem Builds HealthSync.apk. Double-click this file or run it from a terminal.
rem Uses the JDK, Android SDK and Gradle from ..\.tools. Everything goes to build-log.txt.
setlocal
cd /d "%~dp0"
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "TOOLS=%ROOT%\.tools"
set "JAVA_HOME=%TOOLS%\jdk-21"
set "SDK=%TOOLS%\android-sdk"
set "LOG=%~dp0build-log.txt"

echo Build started %date% %time% > "%LOG%"
echo Building HealthSync, this takes a few minutes the first time...

if not exist "%JAVA_HOME%\bin\java.exe" (
    echo JDK not found in %JAVA_HOME% >> "%LOG%"
    goto :fail
)
if not exist "%SDK%\platforms" (
    echo Android SDK not found in %SDK% >> "%LOG%"
    goto :fail
)
rem Gradle reads the SDK location from local.properties
set "SDK_FWD=%SDK:\=/%"
> local.properties echo sdk.dir=%SDK_FWD%

if not exist gradlew.bat (
    echo Creating Gradle wrapper... >> "%LOG%"
    call "%TOOLS%\gradle-9.6.0\bin\gradle.bat" wrapper --gradle-version 9.6.0 >> "%LOG%" 2>&1
    if not exist gradlew.bat goto :fail
)

call gradlew.bat assembleDebug >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

copy /y app\build\outputs\apk\debug\app-debug.apk "%ROOT%\HealthSync.apk" >> "%LOG%"
echo BUILD OK >> "%LOG%"
echo.
echo Done: %ROOT%\HealthSync.apk
pause
exit /b 0

:fail
echo BUILD FAILED >> "%LOG%"
echo.
echo Build failed, details in %LOG%
pause
exit /b 1
