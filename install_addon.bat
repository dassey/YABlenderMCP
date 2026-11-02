@echo off
setlocal

set SRC=%~dp0addon
set ZIP=%~dp0yab-mcp-addon.zip
set DEST=%APPDATA%\Blender Foundation\Blender\5.1\scripts\addons\yab_mcp

:: Versions before 2.1 were installed as "blendermcp"; install.py replaces them and keeps the settings
if exist "%APPDATA%\Blender Foundation\Blender\5.1\scripts\addons\blendermcp" (
    echo An older version is installed under the old name "blendermcp".
    echo Close Blender and run:  python "%~dp0install.py"
    goto :end
)

:: Check if addon is already installed in Blender
if exist "%DEST%" (
    echo Addon found at %DEST%
    echo Syncing addon files...
    xcopy /E /I /Y "%SRC%" "%DEST%"
    echo Done! Restart Blender to pick up changes.
    goto :end
)

:: Not installed yet - build the zip (files must sit inside a yab_mcp\ folder)
echo Building yab-mcp-addon.zip...
python "%~dp0build_addon.py"
if errorlevel 1 (
    echo Could not build yab-mcp-addon.zip. Make sure Python is on PATH.
    goto :end
)

echo.
echo Next steps:
echo   1. Open Blender 5.1
echo   2. Edit ^> Preferences ^> Add-ons
echo   3. Click dropdown arrow ^> Install from Disk...
echo   4. Browse to: %ZIP%
echo   5. Enable "YABlenderMCP" in the addon list

:end
pause
