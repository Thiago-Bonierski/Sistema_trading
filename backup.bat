@echo off
rem backup.bat - copia historico.db, ml_model.joblib e runtime_config.json
rem para backups\backup_YYYY-MM-DD_HH-MM\ (duplo clique no Windows).
setlocal
cd /d "%~dp0"
chcp 65001 >nul

for /f %%S in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm"') do set "STAMP=%%S"
if not defined STAMP (
    echo [ERRO] Nao foi possivel obter a data/hora.
    goto fail
)

set "DEST=backups\backup_%STAMP%"
if not exist "backups" mkdir "backups"
if not exist "%DEST%" mkdir "%DEST%"
if errorlevel 1 (
    echo [ERRO] Nao foi possivel criar %DEST%
    goto fail
)

echo [INFO] Backup em %DEST%
for %%F in (historico.db ml_model.joblib runtime_config.json) do (
    if exist "%%F" (
        copy /y "%%F" "%DEST%\%%F" >nul
        if errorlevel 1 (
            echo [ERRO] Falha ao copiar %%F
        ) else (
            echo [OK] %%F
        )
    ) else (
        echo [AVISO] %%F ausente - ignorado
    )
)

echo.
echo [OK] Backup concluido.
pause
exit /b 0

:fail
echo.
echo [ERRO] Backup abortado.
pause
exit /b 1
