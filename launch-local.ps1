[CmdletBinding()]
param(
    [string]$GameDir = "",
    [string]$Python = "python",
    [string]$ServerHost = "127.0.0.1",
    [int]$ServerPort = 2627,
    [int]$ServerWaitSeconds = 20,
    [string[]]$ClientArgs = @("-root", "-windowed"),
    [switch]$NoServer,
    [switch]$NoClient,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Resolve-RequiredPath {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$Description
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Description not found: $Path"
    }

    return (Resolve-Path -LiteralPath $Path).Path
}

function Escape-SingleQuoted {
    param([string]$Value)
    return $Value.Replace("'", "''")
}

function Wait-ForTcpPort {
    param(
        [Parameter(Mandatory=$true)][string]$HostName,
        [Parameter(Mandatory=$true)][int]$Port,
        [Parameter(Mandatory=$true)][int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $client = [System.Net.Sockets.TcpClient]::new()
        try {
            $connect = $client.BeginConnect($HostName, $Port, $null, $null)
            if ($connect.AsyncWaitHandle.WaitOne(500)) {
                $client.EndConnect($connect)
                return $true
            }
        }
        catch {
        }
        finally {
            $client.Close()
        }

        Start-Sleep -Milliseconds 250
    }

    return $false
}

$RepoRoot = Resolve-RequiredPath -Path $PSScriptRoot -Description "Wulf-Forge directory"
if ([string]::IsNullOrWhiteSpace($GameDir)) {
    $GameDir = Join-Path $RepoRoot "client"
}

$ServerScript = Resolve-RequiredPath -Path (Join-Path $RepoRoot "main.py") -Description "Server script"
$ResolvedGameDir = Resolve-RequiredPath -Path $GameDir -Description "Wulfram II game directory"
$ClientExe = Resolve-RequiredPath -Path (Join-Path $ResolvedGameDir "wulfram2.exe") -Description "Wulfram II client"

Write-Host "[Wulf-Forge] Repo:   $RepoRoot"
Write-Host "[Wulf-Forge] Client: $ClientExe"
Write-Host "[Wulf-Forge] Server: $ServerHost`:$ServerPort"

if ($DryRun) {
    Write-Host "[Wulf-Forge] Dry run only."
    Write-Host "[Wulf-Forge] Would start server: $Python $ServerScript"
    Write-Host "[Wulf-Forge] Would start client: $ClientExe $($ClientArgs -join ' ')"
    exit 0
}

if (-not $NoServer) {
    $repoArg = Escape-SingleQuoted $RepoRoot
    $pythonArg = Escape-SingleQuoted $Python
    $serverCommand = "Set-Location -LiteralPath '$repoArg'; & '$pythonArg' 'main.py'"

    Write-Host "[Wulf-Forge] Starting server..."
    Start-Process `
        -FilePath "powershell.exe" `
        -WorkingDirectory $RepoRoot `
        -ArgumentList @("-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $serverCommand)

    Write-Host "[Wulf-Forge] Waiting for TCP $ServerHost`:$ServerPort..."
    if (-not (Wait-ForTcpPort -HostName $ServerHost -Port $ServerPort -TimeoutSeconds $ServerWaitSeconds)) {
        throw "Server did not open TCP $ServerHost`:$ServerPort within $ServerWaitSeconds seconds."
    }
}

if (-not $NoClient) {
    Write-Host "[Wulf-Forge] Launching client with: $($ClientArgs -join ' ')"
    Start-Process `
        -FilePath $ClientExe `
        -WorkingDirectory $ResolvedGameDir `
        -ArgumentList $ClientArgs
}
