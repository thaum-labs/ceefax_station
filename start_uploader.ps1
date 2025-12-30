# Ceefax Station Uploader - Auto Configuration Script
# This script automatically reads your config and uploads to the public tracker
# Run this from the repository root directory

# Read config from radio_config.json
$configPath = "ceefax\radio_config.json"
if (Test-Path $configPath) {
    $config = Get-Content $configPath | ConvertFrom-Json
    $callsign = $config.callsign
    $grid = $config.grid
} else {
    Write-Host "Error: ceefax/radio_config.json not found. Please configure your station first." -ForegroundColor Red
    Write-Host "Create the file with your callsign and grid square." -ForegroundColor Yellow
    exit 1
}

# Default to production server (no configuration needed)
$server = "https://ceefaxstation.com"
# Token is optional - public uploads are allowed

Write-Host "=== Ceefax Station Uploader ===" -ForegroundColor Cyan
Write-Host "Server: $server" -ForegroundColor Green
Write-Host "Callsign: $callsign" -ForegroundColor Green
Write-Host "Grid: $grid" -ForegroundColor Green
Write-Host ""
Write-Host "Starting uploader (watching for new log files)..." -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop" -ForegroundColor Yellow
Write-Host ""

# Run the uploader (will watch for new files continuously)
# Token is optional - public uploads are allowed
python -m ceefaxstation upload --server $server --callsign $callsign --grid $grid

