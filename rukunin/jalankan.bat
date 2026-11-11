@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  echo ========================================================
  echo   RUKUN — Smart RT Digital
  echo   Server sedang berjalan...
  echo   Buka di browser: http://localhost:5000
  echo   Tekan Ctrl+C untuk menghentikan server.
  echo ========================================================
  echo.
  echo Memeriksa modul yang dibutuhkan...
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
  ".venv\Scripts\python.exe" run.py
  pause
  exit /b 0
)

where py >nul 2>nul
if not errorlevel 1 (
  set PY_CMD=py
  goto :VENV
)

where python >nul 2>nul
if not errorlevel 1 (
  set PY_CMD=python
  goto :VENV
)

echo Python belum terpasang atau belum masuk PATH.
echo Install dari python.org dan centang "Add Python to PATH".
pause
exit /b 1

:VENV
echo Membuat virtual environment dengan %PY_CMD%...
%PY_CMD% -m venv .venv || (echo Gagal membuat venv & pause & exit /b 1)
call .venv\Scripts\activate.bat
echo Memasang dependensi...
python -m pip install -q -r requirements.txt || (echo Gagal pip install. Cek koneksi internet. & pause & exit /b 1)

echo.
echo ========================================================
echo   RUKUN — Smart RT Digital
echo   Buka di browser: http://localhost:5000
echo   Tekan Ctrl+C untuk menghentikan server.
echo ========================================================
echo.
python run.py
pause
