@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Literature Search Workbench v0.2 - Windows

echo ==========================================
echo   Literature Search Workbench v0.2
echo   PubMed Full Retrieval + Covidence RIS
echo ==========================================
echo.
echo [1/3] Checking 64-bit Python 3.11/3.12/3.13...
set "APP_PYTHON="
where py >nul 2>nul
if not errorlevel 1 (
  for %%V in (3.12 3.13 3.11) do (
    if not defined APP_PYTHON (
      py -%%V -c "import sys;sys.exit(0 if sys.maxsize>2**32 else 1)" >nul 2>nul
      if not errorlevel 1 set "APP_PYTHON=py -%%V"
    )
  )
)
if not defined APP_PYTHON (
  where python >nul 2>nul
  if not errorlevel 1 (
    python -c "import sys;sys.exit(0 if (3,11)<=sys.version_info[:2]<=(3,13) and sys.maxsize>2**32 else 1)" >nul 2>nul
    if not errorlevel 1 set "APP_PYTHON=python"
  )
)
if not defined APP_PYTHON goto python_missing
%APP_PYTHON% --version

set "ENV_PY=.venv_compatible\Scripts\python.exe"
if exist "%ENV_PY%" (
  "%ENV_PY%" -c "import sys;sys.exit(0 if (3,11)<=sys.version_info[:2]<=(3,13) and sys.maxsize>2**32 else 1)" >nul 2>nul
  if errorlevel 1 (
    echo Existing environment has an incompatible Python; rebuilding...
    rmdir /s /q ".venv_compatible"
  )
)
if not exist "%ENV_PY%" (
  echo Creating Python environment...
  %APP_PYTHON% -m venv ".venv_compatible"
  if errorlevel 1 goto fail
)

echo.
echo [2/3] Installing packages using prebuilt wheels...
"%ENV_PY%" -m pip install --disable-pip-version-check --only-binary=:all: -r requirements.txt
if errorlevel 1 goto fail

echo.
echo [3/3] Starting website: http://127.0.0.1:8501
echo First launch may ask for Email. Leave it blank and press Enter.
echo KEEP THIS BLACK WINDOW OPEN while using the website.
echo.
"%ENV_PY%" -m streamlit run app.py --server.address 127.0.0.1
if errorlevel 1 goto fail
exit /b 0

:python_missing
echo ERROR: Compatible 64-bit Python was not found.
echo Install Python 3.12 (64-bit) from https://www.python.org/downloads/windows/
echo It can coexist with any newer Python you already have.
goto fail

:fail
echo.
echo Setup or launch failed. Screenshot the last 20 lines and ask ChatGPT.
pause
exit /b 1
