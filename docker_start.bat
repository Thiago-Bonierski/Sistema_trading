@echo off
rem docker_start.bat - sobe backend + painel via Docker Compose no Windows.
rem Duplo clique: inicia o Docker Desktop se estiver parado, aguarda o backend
rem ficar saudavel e abre http://localhost:8080 no navegador padrao.
setlocal
cd /d "%~dp0"
chcp 65001 >nul

rem ---------------------------------------------------------------------------
rem 1. Localizar o Compose (plugin "docker compose" ou legado "docker-compose")
rem ---------------------------------------------------------------------------
docker compose version >nul 2>&1
if not errorlevel 1 goto compose_ok
docker-compose version >nul 2>&1
if not errorlevel 1 goto compose_legacy
echo [ERRO] Docker Compose nao encontrado.
echo        Instale o Docker Desktop: https://www.docker.com/products/docker-desktop/
goto fail

:compose_ok
set "DC=docker compose"
goto check_daemon

:compose_legacy
set "DC=docker-compose"
goto check_daemon

rem ---------------------------------------------------------------------------
rem 2. Garantir que o Docker Desktop esteja rodando
rem ---------------------------------------------------------------------------
:check_daemon
docker info >nul 2>&1
if not errorlevel 1 goto daemon_ok

echo [INFO] Docker Desktop nao esta rodando. Iniciando...
if not exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
    echo [ERRO] Docker Desktop nao encontrado em:
    echo        %ProgramFiles%\Docker\Docker\Docker Desktop.exe
    goto fail
)
start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"

set /a WAIT=0
:wait_daemon
docker info >nul 2>&1
if not errorlevel 1 goto daemon_ok
set /a WAIT+=1
if %WAIT% GEQ 90 (
    echo [ERRO] Docker Desktop nao ficou pronto apos ~3 minutos.
    goto fail
)
ping -n 3 127.0.0.1 >nul
goto wait_daemon

:daemon_ok
echo [OK] Docker daemon ativo.

rem ---------------------------------------------------------------------------
rem 3. Volumes - criar no host para nao virarem root:root no WSL2
rem ---------------------------------------------------------------------------
for %%D in (docker_data docker_models logs simulation_reports) do (
    if not exist "%%D" mkdir "%%D"
)

rem No Windows, montagens NTFS aparecem como root:root dentro da VM WSL2.
rem Essas variaveis sao passadas como build args para o Dockerfile.
set "USER_UID=0"
set "USER_GID=0"

rem ---------------------------------------------------------------------------
rem 4. Build + subida + healthcheck
rem ---------------------------------------------------------------------------
echo [INFO] Construindo e subindo os containers...
%DC% up -d --build
if errorlevel 1 goto fail

echo [INFO] Aguardando o backend ficar saudavel...
set "STATUS="
set /a WAIT=0
:wait_health
for /f "usebackq tokens=1" %%S in (`docker inspect -f "{{.State.Health.Status}}" trading-requiem-backend 2^>nul`) do set "STATUS=%%S"
if /i "%STATUS%"=="healthy" goto health_ok
set /a WAIT+=1
if %WAIT% GEQ 120 (
    echo [ERRO] Backend nao ficou saudavel a tempo.
    echo        Para diagnosticar: %DC% logs backend
    goto fail
)
ping -n 4 127.0.0.1 >nul
goto wait_health

:health_ok
echo [OK] Backend saudavel.
echo [INFO] Abrindo http://localhost:8080 ...
start "" http://localhost:8080

echo.
echo ==================================================
echo  Painel : http://localhost:8080
echo  API    : http://localhost:5000 - rede interna
echo  Parar  : docker_stop.bat
echo ==================================================
echo.
pause
exit /b 0

:fail
echo.
echo [ERRO] Inicializacao abortada.
pause
exit /b 1
