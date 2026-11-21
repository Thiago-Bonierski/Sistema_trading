@echo off
rem run.bat - lancador oficial no Windows (duplo clique): Flask + Vite.
rem Portas 5000/5173, API, navegador e cleanup sao tratados por
rem scripts\run_panel.ps1. Nao usa Docker, WSL nem Linux.

setlocal
cd /d "%~dp0"
chcp 65001 >nul

rem ---------------------------------------------------------------------------
rem 1. Ambiente Python (venv ou .venv do Windows)
rem ---------------------------------------------------------------------------
if exist "venv\Scripts\activate.bat" (
    set "VENV_DIR=venv"
) else if exist ".venv\Scripts\activate.bat" (
    set "VENV_DIR=.venv"
) else (
    echo [ERRO] venv do Windows nao encontrado ^(venv\Scripts\activate.bat^).
    echo        Crie com: py -3.12 -m venv venv
    goto fail
)

call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERRO] Falha ao ativar o venv ^(%VENV_DIR%^).
    goto fail
)
echo [OK] venv ativado (%VENV_DIR%)

set "TR_PYTHON=%CD%\%VENV_DIR%\Scripts\python.exe"
if not exist "%TR_PYTHON%" (
    echo [ERRO] Python do venv nao encontrado: %TR_PYTHON%
    goto fail
)

"%TR_PYTHON%" -c "import sys; sys.exit(0 if sys.version_info[:2] < (3,15) else 1)"
if errorlevel 1 (
    "%TR_PYTHON%" -c "import sys; print(sys.version)"
    echo [ERRO] Python 3.15 nao e suportado pelo ccxt 4.5.x.
    echo        Use Python 3.12 ou 3.13 e recrie o venv:
    echo          py -3.12 -m venv venv
    echo          venv\Scripts\python.exe -m pip install -r requirements.txt
    goto fail
)

rem ---------------------------------------------------------------------------
rem 2. Dependencias Python (só instala se faltarem)
rem ---------------------------------------------------------------------------
"%TR_PYTHON%" -c "import flask, flask_cors" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Dependencias Python ausentes no venv. Instalando...
    "%TR_PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERRO] Falha ao instalar requirements.txt no venv.
        goto fail
    )
    "%TR_PYTHON%" -c "import flask, flask_cors" >nul 2>&1
    if errorlevel 1 (
        echo [ERRO] flask/flask_cors continuam indisponiveis no venv.
        goto fail
    )
)

where npm >nul 2>&1
if errorlevel 1 (
    echo [ERRO] npm nao encontrado. Instale o Node.js 18+.
    goto fail
)

rem ---------------------------------------------------------------------------
rem 3. Dependencias do frontend (vite.cmd só existe após npm install no Windows)
rem ---------------------------------------------------------------------------
if not exist "frontend\node_modules\.bin\vite.cmd" (
    echo [INFO] Instalando dependencias do frontend no Windows...
    if exist "frontend\node_modules" rmdir /s /q "frontend\node_modules"
    if exist "frontend\package-lock.json" del /q "frontend\package-lock.json"
    pushd frontend
    call npm install --no-audit --no-fund
    if errorlevel 1 (
        popd
        echo [ERRO] Falha ao instalar as dependencias do frontend.
        goto fail
    )
    popd
    echo [OK] Frontend pronto.
)

rem ---------------------------------------------------------------------------
rem 4. Painel (processos, API, navegador e cleanup)
rem ---------------------------------------------------------------------------
echo.
echo ==================================================
echo  Trading Requiem - Painel de Controle
echo  Backend : http://127.0.0.1:5000
echo  Painel  : http://localhost:5173
echo  Pressione qualquer tecla para encerrar tudo.
echo ==================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\run_panel.ps1" -PythonPath "%TR_PYTHON%"
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo [ERRO] Inicializacao abortada.
    pause
)
exit /b %RC%

:fail
echo.
echo [ERRO] Inicializacao abortada.
pause
exit /b 1
