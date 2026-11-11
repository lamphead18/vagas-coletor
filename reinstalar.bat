@echo off
cd /d "%~dp0"
rem Forca a reinstalacao das dependencias na proxima abertura.
if exist ".venv\requirements.instalado" del ".venv\requirements.instalado"
if exist ".venv\instalado.ok" del ".venv\instalado.ok"
call iniciar.bat
