@echo off
setlocal
title Build - Carteira BRN P2P
color 0B
cd /d "%~dp0"

cls
echo.
echo ============================================================
echo    COMPILAR CarteiraBRN.exe
echo ============================================================
echo.

:: Verifica Python
python --version >nul 2>&1
if errorlevel 1 (
    echo    ERRO: Python nao encontrado no PATH.
    echo    Instale em https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Verifica arquivos-fonte
echo [1/4] Verificando arquivos-fonte...
if not exist "server.py"         ( echo    ERRO: server.py nao encontrado & pause & exit /b 1 )
if not exist "ngrok_tunnel.py"   ( echo    ERRO: ngrok_tunnel.py nao encontrado & pause & exit /b 1 )
if not exist "index.html"        ( echo    ERRO: index.html nao encontrado & pause & exit /b 1 )
if not exist "app.js"            ( echo    ERRO: app.js nao encontrado & pause & exit /b 1 )
echo    OK
echo.

:: Verifica / instala PyInstaller
echo [2/4] Verificando PyInstaller...
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo    Instalando PyInstaller...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo    ERRO ao instalar PyInstaller.
        pause
        exit /b 1
    )
)
echo    OK
echo.

:: Limpa builds anteriores
echo [3/4] Limpando builds anteriores...
if exist build rmdir /S /Q build
if exist dist rmdir /S /Q dist
if exist CarteiraBRN.spec del /Q CarteiraBRN.spec
echo    OK
echo.

:: Compila
echo [4/4] Compilando (pode demorar 1-2 minutos)...
python -m PyInstaller --onefile --console --name CarteiraBRN ^
  --add-data "index.html;." ^
  --add-data "app.js;." ^
  --hidden-import=ngrok_tunnel ^
  --hidden-import=aiohttp ^
  --hidden-import=pyngrok ^
  --hidden-import=webbrowser ^
  --collect-all aiohttp ^
  server.py

if errorlevel 1 (
    echo.
    echo    ERRO na compilacao. Veja mensagens acima.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo    COMPILADO COM SUCESSO
echo ============================================================
echo.
echo    Arquivo gerado: dist\CarteiraBRN.exe
echo.
echo    PROXIMOS PASSOS:
echo    1. Copie dist\CarteiraBRN.exe para a pasta raiz do projeto
echo       (junto de COMEÇAR.bat, navegador.txt, ngrok_token.txt,
echo       ngrok_domain.txt)
echo.
echo    2. Rode COMEÇAR.bat para testar.
echo.

:: Copia automaticamente o .exe para a raiz, se ela for diferente
if exist "dist\CarteiraBRN.exe" (
    echo    Copiando CarteiraBRN.exe para a pasta atual...
    copy /Y "dist\CarteiraBRN.exe" "CarteiraBRN.exe" >nul
    echo    OK - CarteiraBRN.exe pronto para uso.
)

echo.
pause
exit /b 0