# ==============================================================================
# SIH26150 Forensic Analysis Tool - Automated Windows Installer
# Run in PowerShell:
#   irm https://raw.githubusercontent.com/BhanuPrasad-2006/sih-26150/main/install.ps1 | iex
# ==============================================================================

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$RELEASE_URL = "https://github.com/BhanuPrasad-2006/sih-26150/releases/download/v1.0.0/SIH-Forensic-Tool-Setup-1.0.0.exe"
$EXPECTED_SHA256 = "A3C8A92AE72D1FF8B489E0F324D3B744F358AD6D5901869FB86536286EDC5780"
$SETUP_FILE = "$env:TEMP\SIH-Forensic-Tool-Setup.exe"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  SIH26150 — Multi-Vendor DVR/NVR Forensic Analysis Tool" -ForegroundColor White
Write-Host "  Automated Windows Installer (v1.0.0)" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/3] Downloading installer from GitHub Releases..." -ForegroundColor Yellow
try {
    Invoke-WebRequest -Uri $RELEASE_URL -OutFile $SETUP_FILE -UseBasicParsing
    Write-Host "      Download complete! Saved to $SETUP_FILE" -ForegroundColor Green
} catch {
    Write-Host "      Download failed from release URL: $_" -ForegroundColor Red
    Write-Host "      Please visit https://github.com/BhanuPrasad-2006/sih-26150/releases" -ForegroundColor White
    exit 1
}

Write-Host "[2/3] Verifying SHA-256 cryptographic authenticity..." -ForegroundColor Yellow
$ACTUAL_SHA256 = (Get-FileHash -Path $SETUP_FILE -Algorithm SHA256).Hash
if ($ACTUAL_SHA256.ToUpper() -eq $EXPECTED_SHA256.ToUpper()) {
    Write-Host "      SHA-256 checksum verified OK!" -ForegroundColor Green
} else {
    Write-Host "      WARNING: Checksum mismatch!" -ForegroundColor Red
    Write-Host "      Expected: $EXPECTED_SHA256" -ForegroundColor Red
    Write-Host "      Actual:   $ACTUAL_SHA256" -ForegroundColor Red
    Write-Host "      Aborting installation." -ForegroundColor Red
    exit 1
}

Write-Host "[3/3] Launching installation wizard..." -ForegroundColor Yellow
Start-Process -FilePath $SETUP_FILE -Wait
Write-Host "      Installation finished!" -ForegroundColor Green
Write-Host ""
Write-Host "You can now launch 'SIH Forensic Tool' from your Desktop or Start Menu." -ForegroundColor Cyan
Write-Host ""
