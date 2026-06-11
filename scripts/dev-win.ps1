param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8765,
    [string]$AuthToken = "dev-token",
    [string]$LogLevel = "INFO",
    [switch]$SkipNpmInstall,
    [switch]$NoDesktop,
    [switch]$Menu
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$PythonDir = Join-Path $RepoRoot "python-service"
$DesktopDir = Join-Path $RepoRoot "apps\desktop"
$VitePort = 1420
$pythonProcess = $null

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found in PATH."
    }
}

function Read-ValueOrDefault {
    param(
        [string]$Prompt,
        [string]$DefaultValue
    )

    $value = Read-Host "$Prompt [$DefaultValue]"
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $DefaultValue
    }
    return $value.Trim()
}

function Read-PortOrDefault {
    param([int]$DefaultValue)

    while ($true) {
        $value = Read-Host "Port [$DefaultValue]"
        if ([string]::IsNullOrWhiteSpace($value)) {
            return $DefaultValue
        }

        $parsed = 0
        if ([int]::TryParse($value, [ref]$parsed) -and $parsed -gt 0 -and $parsed -le 65535) {
            return $parsed
        }

        Write-Host "Please enter a valid port number from 1 to 65535."
    }
}

function Show-Menu {
    Write-Host ""
    Write-Host "open-lingua-bridge Windows dev launcher"
    Write-Host ""
    Write-Host "1. Start Python service and Tauri desktop"
    Write-Host "2. Start Python service and Tauri desktop, skip npm install"
    Write-Host "3. Start Python service only"
    Write-Host "4. Custom host, port, token, and log level"
    Write-Host "5. Exit"
    Write-Host ""

    while ($true) {
        $choice = Read-Host "Choose an option [1-5]"
        switch ($choice) {
            "1" { return }
            "2" {
                $script:SkipNpmInstall = $true
                return
            }
            "3" {
                $script:NoDesktop = $true
                return
            }
            "4" {
                $script:HostName = Read-ValueOrDefault -Prompt "Host" -DefaultValue $script:HostName
                $script:Port = Read-PortOrDefault -DefaultValue $script:Port
                $script:AuthToken = Read-ValueOrDefault -Prompt "Auth token" -DefaultValue $script:AuthToken
                $script:LogLevel = Read-ValueOrDefault -Prompt "Log level" -DefaultValue $script:LogLevel

                $skipInstall = Read-ValueOrDefault -Prompt "Skip npm install? y/n" -DefaultValue "n"
                $script:SkipNpmInstall = $skipInstall -in @("y", "Y", "yes", "YES")

                $serviceOnly = Read-ValueOrDefault -Prompt "Start Python service only? y/n" -DefaultValue "n"
                $script:NoDesktop = $serviceOnly -in @("y", "Y", "yes", "YES")
                return
            }
            "5" {
                Write-Host "Canceled."
                exit 0
            }
            default {
                Write-Host "Please choose a number from 1 to 5."
            }
        }
    }
}

function Wait-Health {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec 2
            if ($response.success -eq $true -and $response.data.status -eq "ok") {
                return
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }

    throw "Python Model Service did not become healthy at $Url within $TimeoutSeconds seconds."
}

function Clear-VitePort {
    param(
        [int]$Port = 1420,
        [int]$TimeoutSeconds = 10
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if (-not $connections) {
            return
        }

        foreach ($conn in $connections) {
            $process = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
            if ($null -ne $process -and $process.ProcessName -in @("node", "vite")) {
                Write-Host ("Port {0} is held by {1} (PID {2}). Stopping it..." -f $Port, $process.ProcessName, $process.Id)
                try {
                    Stop-Process -Id $process.Id -Force -ErrorAction Stop
                } catch {
                    throw ("Failed to stop PID {0} holding port {1}: {2}" -f $process.Id, $Port, $_.Exception.Message)
                }
            } else {
                $ownerName = if ($null -ne $process) { $process.ProcessName } else { "<unknown>" }
                throw ("Port {0} is in use by {1} (PID {2}). Free the port and retry." -f $Port, $ownerName, $conn.OwningProcess)
            }
        }

        Start-Sleep -Milliseconds 500
    }

    throw ("Port {0} stayed busy for more than {1} seconds." -f $Port, $TimeoutSeconds)
}

try {
    if ($Menu -or $PSBoundParameters.Count -eq 0) {
        Show-Menu
    }

    $HealthUrl = "http://$($HostName):$($Port)/health"

    Require-Command "uv"
    if (-not $NoDesktop) {
        Require-Command "npm"
    }

    if (-not (Test-Path -LiteralPath $PythonDir)) {
        throw "Python service directory not found: $PythonDir"
    }
    if (-not (Test-Path -LiteralPath $DesktopDir)) {
        throw "Desktop directory not found: $DesktopDir"
    }

    Clear-VitePort -Port $VitePort

    Write-Host ("Starting Python Model Service on {0}:{1}..." -f $HostName, $Port)
    $env:OLB_AUTH_TOKEN = $AuthToken
    $env:OLB_LOG_LEVEL = $LogLevel
    $pythonProcess = Start-Process `
        -FilePath "uv" `
        -ArgumentList @("run", "olb-model-service", "--host", $HostName, "--port", "$Port", "--auth-token", $AuthToken, "--log-level", $LogLevel) `
        -WorkingDirectory $PythonDir `
        -NoNewWindow `
        -PassThru

    Wait-Health -Url $HealthUrl
    Write-Host "Python Model Service is healthy: $HealthUrl"

    if ($NoDesktop) {
        Write-Host "Python service only mode. Press Ctrl+C to stop the service."
        Wait-Process -Id $pythonProcess.Id
        return
    }

    if (-not $SkipNpmInstall) {
        Write-Host "Installing desktop dependencies if needed..."
        Push-Location $DesktopDir
        try {
            npm install
        } finally {
            Pop-Location
        }
    }

    Write-Host "Starting Tauri desktop app..."
    Push-Location $DesktopDir
    try {
        npm run tauri dev
    } finally {
        Pop-Location
    }
} finally {
    if ($null -ne $pythonProcess -and -not $pythonProcess.HasExited) {
        Write-Host "Stopping Python Model Service..."
        Stop-Process -Id $pythonProcess.Id -Force
    }
}
