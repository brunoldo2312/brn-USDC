@echo off
title Carteira BRN P2P
cd /d "%~dp0"

echo.
echo ============================================
echo   CARTEIRA BRN P2P - Iniciando
echo ============================================
echo.

echo [1/4] Verificando Python...
python --version >nul 2>&1
if errorlevel 1 goto SEM_PYTHON
echo    OK - Python encontrado
echo.

echo [2/4] Verificando aiohttp...
python -c "import aiohttp" >nul 2>&1
if errorlevel 1 (
    echo    Instalando aiohttp...
    python -m pip install aiohttp
)
echo    OK
echo.

echo [3/4] Verificando pyngrok...
python -c "import pyngrok" >nul 2>&1
if errorlevel 1 (
    echo    Instalando pyngrok...
    python -m pip install pyngrok
)
echo    OK
echo.

echo [4/4] Iniciando servidor...
echo.
echo    Local: http://localhost:8080
echo    Aguarde a URL publica aparecer abaixo
echo.
echo    Para PARAR: aperte CTRL+C
echo.
echo ============================================
echo.

start "" cmd /c "timeout /t 3 >nul && start http://localhost:8080"

python server.py

echo.
echo Servidor parado.
pause
exit /b 0

:SEM_PYTHON
echo.
echo    ERRO: Python nao encontrado!
echo    Baixe em: https://www.python.org/downloads/
echo    Marque "Add Python to PATH" na instalacao.
echo.
pause
start https://www.python.org/downloads/
exit /b 1