<#
.SYNOPSIS
    Sobe backend Flask + frontend Vite no Windows e encerra tudo com segurança.

.DESCRIPTION
    Chamado por run.bat. Não usa Docker, WSL nem Linux.

    - limpa processos presos nas portas 5000 e 5173;
    - inicia app.py e `npm run dev` no mesmo console;
    - espera GET /api/status responder 200 e abre o navegador;
    - qualquer tecla (ou Ctrl+C, ou fechar a janela) encerra a árvore inteira.

    Os processos filhos entram em um Windows Job Object com
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: se este script morrer abruptamente,
    o Windows mata backend e frontend — sem processos fantasmas.

.PARAMETER PythonPath
    Caminho do python.exe do venv (fornecido por run.bat).

.PARAMETER SmokeTest
    Sobe tudo, valida a API e encerra sozinho. Usado na validação do launcher.
#>
param(
    [string] $PythonPath = '',
    [switch] $SmokeTest,
    [int] $ApiTimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $Root

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $PythonPath = Join-Path $Root 'venv\Scripts\python.exe'
    if (-not (Test-Path $PythonPath)) {
        $PythonPath = Join-Path $Root '.venv\Scripts\python.exe'
    }
}
if (-not (Test-Path $PythonPath)) {
    throw "Python do venv nao encontrado: $PythonPath"
}

function Write-Step([string] $Message) {
    Write-Host $Message
}

function Free-Port([int[]] $Ports) {
    $listeners = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $Ports -contains $_.LocalPort }
    foreach ($listener in $listeners) {
        $owner = [int] $listener.OwningProcess
        # PIDs 0 (System) e 4 (System Idle) nunca devem ser mortos.
        if ($owner -gt 4) {
            Write-Step "[INFO] Liberando porta $($listener.LocalPort) (PID $owner)..."
            & taskkill /PID $owner /T /F 2>$null | Out-Null
        }
    }
}

# Job Object: kill-on-close garante que fechar a janela não deixe filhos órfãos.
$JobSource = @'
using System;
using System.Runtime.InteropServices;

public static class TradingRequiemJob
{
    [StructLayout(LayoutKind.Sequential)]
    public struct IO_COUNTERS
    {
        public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount;
        public ulong ReadTransferCount, WriteTransferCount, OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct BASIC_LIMITS
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct EXTENDED_LIMITS
    {
        public BASIC_LIMITS BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern IntPtr CreateJobObject(IntPtr attributes, string name);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool SetInformationJobObject(
        IntPtr job, int infoClass, ref EXTENDED_LIMITS info, uint infoLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool CloseHandle(IntPtr handle);
}
'@

if (-not ('TradingRequiemJob' -as [type])) {
    try {
        Add-Type -TypeDefinition $JobSource -ErrorAction Stop
    } catch {
        Write-Warning "Job Object indisponível nesta sessão: $($_.Exception.Message)"
    }
}

$jobHandle = [IntPtr]::Zero
$backend = $null
$frontend = $null

try {
    Write-Step '[INFO] Verificando portas 5000 e 5173...'
    Free-Port @(5000, 5173)

    if ('TradingRequiemJob' -as [type]) {
        $jobHandle = [TradingRequiemJob]::CreateJobObject([IntPtr]::Zero, $null)
        if ($jobHandle -ne [IntPtr]::Zero) {
            $basic = New-Object TradingRequiemJob+BASIC_LIMITS
            # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
            $basic.LimitFlags = 0x2000
            $limits = New-Object TradingRequiemJob+EXTENDED_LIMITS
            $limits.BasicLimitInformation = $basic
            $size = [uint32] [Runtime.InteropServices.Marshal]::SizeOf(
                [type] 'TradingRequiemJob+EXTENDED_LIMITS')
            if (-not [TradingRequiemJob]::SetInformationJobObject(
                    $jobHandle, 9, [ref] $limits, $size)) {
                Write-Warning 'Nao foi possivel configurar o Job Object; usando cleanup manual.'
            }
        } else {
            Write-Warning 'Nao foi possivel criar o Job Object; usando cleanup manual.'
        }
    }

    $env:PYTHONUNBUFFERED = '1'
    $env:PYTHONIOENCODING = 'utf-8'

    Write-Step '[INFO] Iniciando backend (Flask) e frontend (Vite)...'
    $backend = Start-Process -FilePath $PythonPath -ArgumentList @('app.py') `
        -WorkingDirectory $Root -PassThru -NoNewWindow
    $frontend = Start-Process -FilePath 'cmd.exe' `
        -ArgumentList @('/c', 'npm run dev -- --host 127.0.0.1') `
        -WorkingDirectory (Join-Path $Root 'frontend') -PassThru -NoNewWindow

    if ($jobHandle -ne [IntPtr]::Zero) {
        foreach ($child in @($backend, $frontend)) {
            if ($child -and -not [TradingRequiemJob]::AssignProcessToJobObject(
                    $jobHandle, $child.Handle)) {
                Write-Warning "Processo $($child.Id) nao entrou no Job Object; cleanup manual cobre."
            }
        }
    }

    # Ctrl+C vira tecla comum, tratada pelo loop abaixo (evita interrupted state).
    try { [Console]::TreatControlCAsInput = $true } catch { }

    Write-Step '[INFO] Aguardando API em http://127.0.0.1:5000/api/status ...'
    $deadline = (Get-Date).AddSeconds($ApiTimeoutSeconds)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        if ($backend.HasExited) { break }
        try {
            $response = Invoke-WebRequest -Uri 'http://127.0.0.1:5000/api/status' `
                -UseBasicParsing -TimeoutSec 2
            if ([int] $response.StatusCode -eq 200) { $ready = $true; break }
        } catch {
            # API ainda subindo.
        }
        Start-Sleep -Milliseconds 500
    }

    if (-not $ready) {
        throw 'API nao ficou pronta a tempo. Verifique o log do backend acima.'
    }

    Write-Step '[OK] API pronta.'
    if ($SmokeTest) {
        Write-Step '[SMOKE] Validacao concluida; encerrando processos...'
        Start-Sleep -Seconds 2
    } else {
        Start-Process 'http://localhost:5173'
        Write-Step '[INFO] Painel aberto em http://localhost:5173'
        Write-Step '[INFO] Pressione qualquer tecla (ou Ctrl+C) para encerrar tudo.'
        while (-not $backend.HasExited -and -not $frontend.HasExited) {
            $keyAvailable = $false
            try { $keyAvailable = [Console]::KeyAvailable } catch { }
            if ($keyAvailable) {
                try { [Console]::ReadKey($true) | Out-Null } catch { }
                break
            }
            Start-Sleep -Milliseconds 200
        }
        if ($backend.HasExited -or $frontend.HasExited) {
            Write-Warning 'Um dos processos encerrou inesperadamente.'
        }
    }
} catch {
    Write-Host ''
    Write-Host "[ERRO] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    Write-Host ''
    Write-Step '[INFO] Encerrando backend e frontend...'
    foreach ($child in @($backend, $frontend)) {
        if ($null -ne $child -and -not $child.HasExited) {
            & taskkill /PID $child.Id /T /F 2>$null | Out-Null
        }
    }
    # Fechar o handle dispara KILL_ON_JOB_CLOSE para qualquer filho sobrevivente.
    if ($jobHandle -ne [IntPtr]::Zero) {
        [TradingRequiemJob]::CloseHandle($jobHandle) | Out-Null
        $jobHandle = [IntPtr]::Zero
    }
    Start-Sleep -Milliseconds 700
    Free-Port @(5000, 5173)
    Write-Step '[OK] Painel encerrado. Portas 5000 e 5173 liberadas.'
}
