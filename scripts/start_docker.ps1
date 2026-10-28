# Start Docker Desktop safely on this machine, then start Qdrant.
#   powershell -ExecutionPolicy Bypass -File scripts\start_docker.ps1
#
# Why: Docker Desktop 4.34 leaves a stale socket file (run\userAnalyticsOtlpHttp.sock) behind when it
# closes, and Windows will not let it delete that file, so the next start fails with
# "removing stale socket ... The file cannot be accessed by the system". Moving the run folder aside
# (while Docker is stopped) avoids it. Updating Docker Desktop is the permanent fix.

$dockerDir = Join-Path $env:LOCALAPPDATA "Docker"
$run = Join-Path $dockerDir "run"
$running = Get-Process "com.docker.backend" -ErrorAction SilentlyContinue

if (-not $running -and (Get-ChildItem $run -Force -Filter *.sock -ErrorAction SilentlyContinue)) {
    Rename-Item -LiteralPath $run -NewName ("run.old-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
    Write-Host "Moved stale Docker runtime folder aside"
}
# Old moved-aside folders can be removed once they are no longer locked.
Get-ChildItem $dockerDir -Directory -Filter "run.old-*" | ForEach-Object {
    Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
}

if (-not $running) {
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    Write-Host "Starting Docker Desktop..."
}
for ($i = 0; $i -lt 60; $i++) {
    docker version --format "{{.Server.Version}}" *> $null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 3
}
if ($LASTEXITCODE -ne 0) { Write-Host "Docker did not start. Open Docker Desktop and check its message."; exit 1 }

docker compose -f infra/docker-compose.yml up -d
Write-Host "Docker and Qdrant are running. Qdrant dashboard: http://localhost:6333/dashboard"
