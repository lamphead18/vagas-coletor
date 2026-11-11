@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Rode o iniciar.bat pelo menos uma vez antes.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m radar avaliar
pause
