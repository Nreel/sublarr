# Open Sublarr in Browser

Write-Host "Opening Sublarr in browser..." -ForegroundColor Cyan

# Frontend
Write-Host "Opening Frontend: http://localhost:5173" -ForegroundColor Green
Start-Process "http://localhost:5173"

# Backend API
$BackendPort = if ($env:SUBLARR_PORT) { $env:SUBLARR_PORT } else { 5765 }
Write-Host "Opening Backend API: http://localhost:$BackendPort/api/v1/health" -ForegroundColor Green
Start-Process "http://localhost:$BackendPort/api/v1/health"

Write-Host ""
Write-Host "Frontend UI: http://localhost:5173" -ForegroundColor Yellow
Write-Host "Backend API: http://localhost:$BackendPort/api/v1/health" -ForegroundColor Yellow
Write-Host "Backend Docs: http://localhost:$BackendPort/api/v1/config" -ForegroundColor Yellow
