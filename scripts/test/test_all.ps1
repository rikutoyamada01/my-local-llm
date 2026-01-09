# test_all.ps1
# Run all module tests in sequence

param (
    [switch]$Verbose = $false,
    [switch]$SkipSensor = $false,
    [switch]$SkipCognizer = $false,
    [switch]$SkipMemory = $false,
    [switch]$SkipArchiver = $false
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$TestScriptDir = "$PSScriptRoot"

Write-Host "=====================================" -ForegroundColor Magenta
Write-Host "  Module Test Suite" -ForegroundColor Magenta
Write-Host "=====================================" -ForegroundColor Magenta

$Results = @{}

# Test Sensor
if (-not $SkipSensor) {
    try {
        & "$TestScriptDir\test_sensor.ps1" -Verbose:$Verbose
        $Results["Sensor"] = "[PASS]"
    } catch {
        $Results["Sensor"] = "[FAIL] $_"
    }
}

# Test Memory
if (-not $SkipMemory) {
    try {
        & "$TestScriptDir\test_memory.ps1" -Verbose:$Verbose
        $Results["Memory"] = "[PASS]"
    } catch {
        $Results["Memory"] = "[FAIL] $_"
    }
}

# Test Cognizer
if (-not $SkipCognizer) {
    try {
        & "$TestScriptDir\test_cognizer.ps1" -Verbose:$Verbose
        $Results["Cognizer"] = "[PASS]"
    } catch {
        $Results["Cognizer"] = "[FAIL] $_"
    }
}

# Test Archiver
if (-not $SkipArchiver) {
    try {
        & "$TestScriptDir\test_archiver.ps1" -Verbose:$Verbose
        $Results["Archiver"] = "[PASS]"
    } catch {
        $Results["Archiver"] = "[FAIL] $_"
    }
}

# Summary
Write-Host "`n=====================================" -ForegroundColor Magenta
Write-Host "  Test Results Summary" -ForegroundColor Magenta
Write-Host "=====================================" -ForegroundColor Magenta

foreach ($module in $Results.Keys) {
    $result = $Results[$module]
    if ($result -like "*PASS*") {
        Write-Host "$module : $result" -ForegroundColor Green
    } else {
        Write-Host "$module : $result" -ForegroundColor Red
    }
}

Write-Host "=====================================" -ForegroundColor Magenta

# Exit with error if any test failed
$FailedTests = $Results.Values | Where-Object { $_ -like "*FAIL*" }
if ($FailedTests) {
    exit 1
}
