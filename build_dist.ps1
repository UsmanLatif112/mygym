# Build Alpha Fitness Gym desktop app for sharing (dist folder).
# Run from the mygym directory:
#   powershell -ExecutionPolicy Bypass -File .\build_dist.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== Preparing seed database from local SQLite ===" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path "seed" | Out-Null
if (-not (Test-Path "data\mygym_local.db")) {
    Write-Host "ERROR: data\mygym_local.db not found. Pull MySQL data first." -ForegroundColor Red
    exit 1
}
Copy-Item -Force "data\mygym_local.db" "seed\mygym_seed.db"
Write-Host "Updated seed\mygym_seed.db from data\mygym_local.db"

$icon = "static\logo.ico"
if (-not (Test-Path $icon)) {
    Write-Host "WARNING: static\logo.ico missing, using favicon.png" -ForegroundColor Yellow
    $icon = "static\favicon.png"
}
Write-Host "App icon: $icon"

Write-Host "=== Running PyInstaller ===" -ForegroundColor Cyan
pyinstaller --noconfirm --clean --onefile --noconsole `
  --name "AlphaFitnessGym" `
  --icon $icon `
  --add-data "templates;templates" `
  --add-data "static;static" `
  --add-data ".env;." `
  --add-data "seed;seed" `
  --add-data "backups;backups" `
  desktop_launcher.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller failed." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "=== Copying database folders into dist ===" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path "dist\data" | Out-Null
New-Item -ItemType Directory -Force -Path "dist\seed" | Out-Null
New-Item -ItemType Directory -Force -Path "dist\backups" | Out-Null

Copy-Item -Force "data\mygym_local.db" "dist\data\mygym_local.db"
Copy-Item -Force "seed\mygym_seed.db" "dist\seed\mygym_seed.db"

Get-ChildItem "backups\*.sql" -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1 |
  ForEach-Object { Copy-Item -Force $_.FullName "dist\backups\$($_.Name)" }

# Simple note for end users next to the exe
@"
Alpha Fitness Gym - Desktop App

HOW TO USE
1. Keep this whole folder together (do not move only the .exe).
2. Run AlphaFitnessGym.exe

DATABASE (manual copy if online backup fails)
- Full database file:
    data\mygym_local.db
- Spare restore copy:
    seed\mygym_seed.db

If online backup fails, copy data\mygym_local.db to USB / another PC.
When restoring, put that file back as:
    data\mygym_local.db
next to AlphaFitnessGym.exe, then open the app.
"@ | Set-Content -Encoding UTF8 "dist\READ_ME_DATABASE.txt"

Write-Host ""
Write-Host "DONE. Share the entire dist\ folder with the user." -ForegroundColor Green
Write-Host "  dist\AlphaFitnessGym.exe     (logo icon)"
Write-Host "  dist\data\mygym_local.db     (latest gym data - copy/paste backup)"
Write-Host "  dist\seed\mygym_seed.db      (restore seed)"
Write-Host "  dist\backups\"
Write-Host "  dist\READ_ME_DATABASE.txt"
