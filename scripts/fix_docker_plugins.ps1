# fix_docker_plugins.ps1
# Fix Docker CLI plugin issues

$ErrorActionPreference = "Continue"

Write-Host "=== Fixing Docker CLI Plugins ===" -ForegroundColor Cyan

$pluginDir = "$env:USERPROFILE\.docker\cli-plugins"
$invalidPlugins = @("docker-dev.exe", "docker-feedback.exe")

Write-Host "`nChecking plugin directory: $pluginDir" -ForegroundColor Yellow

if (Test-Path $pluginDir) {
    foreach ($plugin in $invalidPlugins) {
        $pluginPath = Join-Path $pluginDir $plugin
        if (Test-Path $pluginPath) {
            Write-Host "  Removing invalid plugin: $plugin" -ForegroundColor Yellow
            Remove-Item $pluginPath -Force
            Write-Host "  [OK] Removed $plugin" -ForegroundColor Green
        } else {
            Write-Host "  [INFO] $plugin not found (already removed)" -ForegroundColor Gray
        }
    }
} else {
    Write-Host "[INFO] Plugin directory does not exist" -ForegroundColor Gray
}

Write-Host "`n[SUCCESS] Plugin cleanup completed" -ForegroundColor Green
Write-Host "Please restart Docker Desktop manually and check if the issue is resolved." -ForegroundColor Cyan
