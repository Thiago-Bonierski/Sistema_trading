@echo off
rem run.bat - sobe o painel completo (backend Flask + frontend Vite) no Windows.
rem Equivalente ao run.sh. Ctrl+C encerra os dois processos e libera as portas 5000 e 5173.

setlocal
cd /d "%~dp0"
chcp 65001 >nul

rem ---------------------------------------------------------------------------
rem 1. Ambiente Python
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
    echo        O ccxt fixa zlib-ng==1.0.0, que nao tem wheel para cp315.
    echo        Use Python 3.12 ou 3.13 e recrie o venv:
    echo          py -3.12 -m venv venv
    echo          venv\Scripts\python.exe -m pip install -r requirements.txt
    goto fail
)

rem ---------------------------------------------------------------------------
rem 2. Dependencias Python (instala no venv se estiverem faltando)
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
rem 3. Dependencias do frontend
rem ---------------------------------------------------------------------------
rem O vite.cmd so existe quando o npm install roda no Windows.
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
rem 4. Backend + frontend em paralelo
rem ---------------------------------------------------------------------------
echo.
echo ==================================================
echo  Trading Requiem - Painel de Controle
echo  Backend : http://127.0.0.1:5000
echo  Painel  : http://127.0.0.1:5173
echo  Ctrl+C encerra os dois processos.
echo ==================================================
echo.

rem Helper temporario em PowerShell: mantem os dois processos no MESMO console
rem (para o Ctrl+C chegar aos dois) e mata a arvore de processos no finally.
set "PS_HELPER=%TEMP%\trading_requiem_run_%RANDOM%.ps1"
echo $ErrorActionPreference = 'Continue' > "%PS_HELPER%"
echo $root = (Get-Location).Path >> "%PS_HELPER%"
echo $py = $env:TR_PYTHON >> "%PS_HELPER%"
echo $env:PYTHONUNBUFFERED = '1' >> "%PS_HELPER%"
echo $env:PYTHONIOENCODING = 'utf-8' >> "%PS_HELPER%"
echo $feDir = Join-Path $root 'frontend' >> "%PS_HELPER%"
echo $backend = Start-Process -FilePath $py -ArgumentList 'app.py' -WorkingDirectory $root -PassThru -NoNewWindow >> "%PS_HELPER%"
echo $frontend = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c npm run dev -- --host 127.0.0.1' -WorkingDirectory $feDir -PassThru -NoNewWindow >> "%PS_HELPER%"
echo try { >> "%PS_HELPER%"
echo $alive = $true >> "%PS_HELPER%"
echo while ($alive) { >> "%PS_HELPER%"
echo $p1 = Get-Process -Id $backend.Id -ErrorAction SilentlyContinue >> "%PS_HELPER%"
echo $p2 = Get-Process -Id $frontend.Id -ErrorAction SilentlyContinue >> "%PS_HELPER%"
echo if ($null -eq $p1 -or $null -eq $p2) { $alive = $false } >> "%PS_HELPER%"
echo Start-Sleep -Milliseconds 500 >> "%PS_HELPER%"
echo } >> "%PS_HELPER%"
echo } >> "%PS_HELPER%"
echo finally { >> "%PS_HELPER%"
echo Write-Host '' >> "%PS_HELPER%"
echo Write-Host '[INFO] Encerrando backend e frontend...' >> "%PS_HELPER%"
echo cmd /c "taskkill /PID $backend.Id /T /F ^>nul 2^>^&1" >> "%PS_HELPER%"
echo cmd /c "taskkill /PID $frontend.Id /T /F ^>nul 2^>^&1" >> "%PS_HELPER%"
echo Write-Host '[OK] Painel encerrado. Portas 5000 e 5173 liberadas.' >> "%PS_HELPER%"
echo } >> "%PS_HELPER%"

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_HELPER%"
set "RC=%ERRORLEVEL%"
del /q "%PS_HELPER%" >nul 2>&1

rem Mantem a janela aberta quando executado por duplo clique.
echo.
pause
exit /b %RC%

:fail
echo.
echo [ERRO] Inicializacao abortada.
pause
exit /b 1
