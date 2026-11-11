@echo off
setlocal
cd /d "%~dp0"
title Radar de Vagas

rem Escolhe o Python: prefere 3.12, depois o padrao do launcher "py", depois "python".
set "PY="
py -3.12 -c "" >nul 2>nul && set "PY=py -3.12"
if not defined PY py -3 -c "" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "" >nul 2>nul && set "PY=python"
if not defined PY goto sem_python

if not exist ".venv\Scripts\python.exe" (
  echo Criando ambiente virtual em .venv ...
  %PY% -m venv .venv
  if errorlevel 1 goto erro
)

rem Reinstala as dependencias sempre que o requirements.txt mudar (ex.: depois de uma atualizacao).
if not exist ".venv\requirements.instalado" goto instalar
fc /b "requirements.txt" ".venv\requirements.instalado" >nul 2>nul
if errorlevel 1 goto instalar
goto pronto

:instalar
echo Instalando dependencias - leva alguns minutos ...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt -q
if errorlevel 1 goto erro
".venv\Scripts\python.exe" -m pip install -r requirements-jobspy.txt -q
if errorlevel 1 echo AVISO: python-jobspy nao instalou. A Gupy funciona; Indeed, Glassdoor e LinkedIn ficam sem coletar.
copy /y "requirements.txt" ".venv\requirements.instalado" >nul

:pronto
if not exist "config.yaml" (
  copy "config.example.yaml" "config.yaml" >nul
  echo Criei o config.yaml. Edite os termos de busca nele e reinicie.
)
if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Criei o .env. Cole nele as suas chaves de API e reinicie.
)

".venv\Scripts\python.exe" -m radar
if errorlevel 1 pause
exit /b 0

:sem_python
echo Python nao encontrado.
echo Instale o Python em https://www.python.org/downloads/ e marque "Add python.exe to PATH".
pause
exit /b 1

:erro
echo Algo deu errado na instalacao. Veja as mensagens acima.
pause
exit /b 1
