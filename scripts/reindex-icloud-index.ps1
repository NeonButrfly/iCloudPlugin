$ErrorActionPreference = "Stop"

$repoRoot = if ($env:ICLOUDPLUGIN_ROOT) { $env:ICLOUDPLUGIN_ROOT } else { "/opt/iCloudPlugin" }
$servicePort = if ($env:SERVICE_PORT) { $env:SERVICE_PORT } else { "8080" }
$postgresUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "icloud" }
$postgresDb = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "icloud_index" }

Set-Location $repoRoot

docker compose up -d postgres service worker | Out-Null

docker compose exec -T postgres psql `
  -U $postgresUser `
  -d $postgresDb `
  -v ON_ERROR_STOP=1 `
  -c "TRUNCATE TABLE extracted_contents, files, jobs, sync_runs RESTART IDENTITY CASCADE;"

curl.exe -fsS -X POST "http://127.0.0.1:$servicePort/refresh"
Write-Output ""
curl.exe -fsS "http://127.0.0.1:$servicePort/refresh/status"
Write-Output ""
