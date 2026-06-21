@echo off
python --version >nul 2>&1
if %errorlevel%==0 (
    python src\main.py
    goto :end
)
py --version >nul 2>&1
if %errorlevel%==0 (
    py src\main.py
    goto :end
)
echo Python is not installed or not in PATH. Install Python from https://python.org
echo.
:end
pause
