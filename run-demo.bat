@echo off
rem ---------------------------------------------------------------------------
rem PLATEAU Hiroshima x Isaac Sim - G1 walking demo launcher (GUI free-view)
rem
rem   Double-click : GUI mode, walk from Kamiyacho along Aioi-dori
rem   From a shell : run-demo.bat [extra args passed to g1_hiroshima_demo.py]
rem     run-demo.bat --spawn -60 -260 --heading 90
rem     run-demo.bat --headless --video --video_length 450
rem ---------------------------------------------------------------------------
setlocal
chcp 65001 >nul

set "PYTHON=C:\projects\humanoid-sim\.venv-isaac\Scripts\python.exe"
set "OMNI_KIT_ACCEPT_EULA=yes"
set "PYTHONUTF8=1"

cd /d "%~dp0"

if not exist "%PYTHON%" (
    echo [error] Isaac Sim venv python not found:
    echo         %PYTHON%
    echo         See README.md - the venv is shared with C:\projects\humanoid-sim
    pause
    exit /b 1
)

if not exist "data\usd\hiroshima_city.usd" (
    echo [error] City stage not found: data\usd\hiroshima_city.usd
    echo         Run the CityGML -^> OBJ -^> USD pipeline first. See README.md
    pause
    exit /b 1
)

rem No args -> GUI free-view defaults. 200000 steps is effectively "until you close it".
set "ARGS=%*"
if "%ARGS%"=="" set "ARGS=--steps 200000 --spawn 700 -128 --heading -17"

echo [run] python tools\g1_hiroshima_demo.py %ARGS%
echo [run] Isaac Sim window takes 1-2 min to appear on first launch.
echo [run] Viewport: right-drag = look, WASD = fly, wheel = dolly. Ctrl+C here to stop.
echo.

"%PYTHON%" -X utf8 -u tools\g1_hiroshima_demo.py %ARGS%

echo.
echo [run] finished with exit code %ERRORLEVEL%
pause
