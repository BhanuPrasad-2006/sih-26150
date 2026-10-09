# SIH26150 — Multi-Vendor DVR/NVR Forensic Analysis Tool
# Automated Windows Installer & Downloader
$ErrorActionPreference = 'Stop'

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host " SIH Forensic Analysis Tool (SIH26150) - Installer" -ForegroundColor Cyan
Write-Host " Team Espada | Multi-Vendor DVR/NVR Video Recovery" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

$installerUrl = "https://github.com/BhanuPrasad-2006/sih-26150/releases/download/v2.0.0/SIH-Forensic-Tool-Setup-2.0.0.exe"
$destFile = Join-Path $env:TEMP "SIH-Forensic-Tool-Setup-2.0.0.exe"

Write-Host "[1/3] Downloading Windows installer (~188 MB)..." -ForegroundColor Yellow
Write-Host "      Source: $installerUrl" -ForegroundColor Gray

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
        & curl.exe -L -o "$destFile" "$installerUrl" --progress-bar
    } else {
        Invoke-WebRequest -Uri $installerUrl -OutFile $destFile -UseBasicParsing
    }
} catch {
    Write-Host "[ERROR] Download failed: $_" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path "$destFile") -or ((Get-Item "$destFile").Length -lt 10000000)) {
    Write-Host "[ERROR] Downloaded file is invalid or incomplete." -ForegroundColor Red
    exit 1
}

Write-Host "[2/3] Verification passed! Launching Setup Wizard..." -ForegroundColor Green
Write-Host "[3/3] Follow on-screen wizard to create Desktop shortcut." -ForegroundColor Green
Write-Host ""
Start-Process "$destFile"
