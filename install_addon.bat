@echo off
setlocal

set SRC=%~dp0addon
set ZIP=%~dp0addon.zip
set DEST=%APPDATA%\Blender Foundation\Blender\5.1\scripts\addons\blendermcp

:: Check if addon is already installed in Blender
if exist "%DEST%" (
    echo Addon found at %DEST%
    echo Syncing addon files...
    xcopy /E /I /Y "%SRC%" "%DEST%"
    echo Done! Restart Blender to pick up changes.
    goto :end
)

:: Not installed yet - build the zip (files must sit inside a blendermcp\ folder)
echo Building addon.zip...
python "%~dp0build_addon.py"
if errorlevel 1 (
    echo Could not build addon.zip. Make sure Python is on PATH.
    goto :end
)

echo.
echo Next steps:
echo   1. Open Blender 5.1
echo   2. Edit ^> Preferences ^> Add-ons
echo   3. Click dropdown arrow ^> Install from Disk...
echo   4. Browse to: %ZIP%
echo   5. Enable "BlenderMCP" in the addon list

:end
pause
