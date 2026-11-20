@echo off
rem docker_stop.bat - encerra os containers do painel com duplo clique.
setlocal
cd /d "%~dp0"
chcp 65001 >nul

docker compose version >nul 2>&1
if not errorlevel 1 goto compose_ok
docker-compose version >nul 2>&1
if not errorlevel 1 goto compose_legacy
echo [ERRO] Docker Compose nao encontrado.
goto fail

:compose_ok
set "DC=docker compose"
goto stop

:compose_legacy
set "DC=docker-compose"
goto stop

:stop
echo [INFO] Encerrando containers...
%DC% down
if errorlevel 1 goto fail
echo [OK] Containers encerrados.
echo [OK] Porta 8080 liberada.
echo.
pause
exit /b 0

:fail
echo.
echo [ERRO] Falha ao encerrar os containers.
pause
exit /b 1
