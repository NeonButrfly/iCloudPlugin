param(
    [switch]$Yes,
    [switch]$DryRun,
    [string]$EnvFile,
    [string]$ComposeFile,
    [string]$ComposeProject,
    [string]$ServiceUrl
)

$ErrorActionPreference = "Stop"

function Write-LogLine {
    param([string]$Message)
    Write-Output ("{0} {1}" -f (Get-Date).ToString("o"), $Message)
}

function Fail-Script {
    param([string]$Message)
    throw $Message
}

function Load-EnvFile {
    param([string]$Path)

    if (-not $Path -or -not (Test-Path $Path)) {
        return
    }

    foreach ($rawLine in Get-Content -Path $Path) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }
        $parts = $line -split "=", 2
        if ($parts.Length -ne 2) {
            continue
        }
        $name = $parts[0].Trim()
        $value = $parts[1].Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        if (-not (Test-Path "Env:$name")) {
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}

function Invoke-Step {
    param(
        [string]$Description,
        [string[]]$Command
    )

    if ($DryRun) {
        Write-LogLine "DRY RUN: $Description"
        Write-Output ("  {0}" -f ($Command -join " "))
        return
    }

    Write-LogLine $Description
    & $Command[0] $Command[1..($Command.Length - 1)]
}

function Mask-SensitiveParts {
    param([string[]]$Parts)

    $masked = @()
    for ($index = 0; $index -lt $Parts.Length; $index++) {
        $part = $Parts[$index]
        if ($part -eq "Authorization: Bearer $script:PluginApiToken" -and $script:PluginApiToken) {
            $masked += "Authorization: Bearer [redacted]"
        } else {
            $masked += $part
        }
    }
    return ,$masked
}

function Test-PostgresServiceRunning {
    $output = & docker compose -p $script:ComposeProject --env-file $script:EnvFile -f $script:ComposeFile ps --status running --services 2>$null
    return $LASTEXITCODE -eq 0 -and ($output -split "`r?`n") -contains $script:PostgresService
}

function Invoke-PostgresCommand {
    param([string[]]$Command)

    if (Test-PostgresServiceRunning) {
        & docker compose -p $script:ComposeProject --env-file $script:EnvFile -f $script:ComposeFile exec -T $script:PostgresService @Command
        return
    }

    & docker run --rm --network host -e "PGPASSWORD=$script:PostgresPassword" postgres:16 @Command
}

function Wait-ForServiceHealth {
    $deadline = (Get-Date).AddSeconds($script:ServiceStartTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $null = & curl.exe -fsS "$($script:ServiceUrl.TrimEnd('/'))/health"
            if ($LASTEXITCODE -eq 0) {
                return
            }
        } catch {
        }
        Start-Sleep -Seconds 2
    }

    Fail-Script "Service did not become healthy at $($script:ServiceUrl.TrimEnd('/'))/health within $($script:ServiceStartTimeoutSeconds)s."
}

$script:RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$script:EnvFile = if ($EnvFile) { $EnvFile } else { Join-Path $script:RepoRoot "deploy/roles/cloudsync/.env.live" }
$script:ComposeFile = if ($ComposeFile) { $ComposeFile } else { Join-Path $script:RepoRoot "deploy/roles/cloudsync/docker-compose.yml" }
$script:ComposeProject = if ($ComposeProject) { $ComposeProject } else { "icloudplugin" }

Set-Location $script:RepoRoot
Load-EnvFile -Path $script:EnvFile

$script:PostgresService = if ($env:POSTGRES_SERVICE) { $env:POSTGRES_SERVICE } else { "postgres" }
$script:PostgresHost = if ($env:POSTGRES_HOST) { $env:POSTGRES_HOST } else { "postgres" }
$script:PostgresPort = if ($env:POSTGRES_PORT) { $env:POSTGRES_PORT } else { "5432" }
$script:PostgresUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "icloud" }
$script:PostgresPassword = if ($env:POSTGRES_PASSWORD) { $env:POSTGRES_PASSWORD } else { "change-me" }
$script:PostgresDb = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "icloud_index" }
$script:PluginApiToken = if ($env:PLUGIN_API_TOKEN) { $env:PLUGIN_API_TOKEN } else { "" }
$script:PluginServiceUrl = if ($env:PLUGIN_SERVICE_URL) { $env:PLUGIN_SERVICE_URL } else { "" }
$script:ServicePort = if ($env:SERVICE_PORT) { $env:SERVICE_PORT } else { "8080" }
$script:ServiceUrl = if ($ServiceUrl) { $ServiceUrl } elseif ($env:SERVICE_URL) { $env:SERVICE_URL } elseif ($script:PluginServiceUrl) { $script:PluginServiceUrl } else { "http://127.0.0.1:$script:ServicePort" }
$script:ServiceStartTimeoutSeconds = if ($env:SERVICE_START_TIMEOUT_SECONDS) { [int]$env:SERVICE_START_TIMEOUT_SECONDS } else { 60 }

if (-not $DryRun -and -not $Yes) {
    Fail-Script "This action is destructive. Re-run with -Yes to confirm, or use -DryRun first."
}

if ($script:PostgresHost -eq $script:PostgresService) {
    Invoke-Step "Starting local postgres plus cloudsync runtime services" @(
        "docker", "compose", "-p", $script:ComposeProject, "--env-file", $script:EnvFile, "-f", $script:ComposeFile,
        "up", "-d", "postgres", "migrate", "service", "worker", "classification-worker"
    )
} else {
    Invoke-Step "Starting cloudsync runtime services against remote postgres" @(
        "docker", "compose", "-p", $script:ComposeProject, "--env-file", $script:EnvFile, "-f", $script:ComposeFile,
        "up", "-d", "--no-deps", "service", "worker", "classification-worker"
    )
}

if (-not $DryRun) {
    Wait-ForServiceHealth
}

$truncateSql = "TRUNCATE TABLE classification_jobs, classification_states, extracted_contents, files, jobs, sync_runs RESTART IDENTITY CASCADE;"
if ($DryRun) {
    Write-LogLine "DRY RUN: truncate cloud-vault index tables"
    Write-Output "  SQL: $truncateSql"
} else {
    Write-LogLine "Truncating cloud-vault index tables"
    Invoke-PostgresCommand @(
        "psql",
        "-h", $script:PostgresHost,
        "-p", $script:PostgresPort,
        "-U", $script:PostgresUser,
        "-d", $script:PostgresDb,
        "-v", "ON_ERROR_STOP=1",
        "-c", $truncateSql
    )
}

$refreshArgs = @("-fsS", "-X", "POST")
if ($script:PluginApiToken) {
    $refreshArgs += @("-H", "Authorization: Bearer $script:PluginApiToken")
}
$refreshArgs += "$($script:ServiceUrl.TrimEnd('/'))/refresh"

if ($DryRun) {
    Write-LogLine "DRY RUN: queue fresh refresh run"
    Write-Output ("  curl.exe {0}" -f ((Mask-SensitiveParts $refreshArgs) -join " "))
} else {
    Write-LogLine "Queueing fresh refresh run"
    & curl.exe @refreshArgs
    Write-Output ""
}

$statusArgs = @("-fsS", "$($script:ServiceUrl.TrimEnd('/'))/refresh/status")
if ($DryRun) {
    Write-LogLine "DRY RUN: print refresh status"
    Write-Output ("  curl.exe {0}" -f ($statusArgs -join " "))
} else {
    Write-LogLine "Current refresh status"
    & curl.exe @statusArgs
    Write-Output ""
}
