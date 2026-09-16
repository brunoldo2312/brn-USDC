@echo off
chcp 65001 >nul
title Carteira BRN P2P - Servidor Local
color 0A

echo.
echo ============================================================
echo    CARTEIRA BRN P2P - Iniciando Sistema
echo ============================================================
echo.

:: ============================================================
:: PASSO 1 - Verifica se o Python esta instalado
:: ============================================================
echo [1/5] Verificando Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo    ERRO: Python nao foi encontrado!
    echo.
    echo    Voce precisa instalar o Python primeiro:
    echo    https://www.python.org/downloads/
    echo.
    echo    IMPORTANTE: Marque a caixa "Add Python to PATH"
    echo.
    pause
    start https://www.python.org/downloads/
    exit /b 1
)
echo    OK - Python instalado!
echo.

:: ============================================================
:: PASSO 2 - Verifica se o aiohttp esta instalado
:: ============================================================
echo [2/5] Verificando dependencias (aiohttp)...
python -c "import aiohttp" >nul 2>&1
if errorlevel 1 (
    echo    aiohttp nao encontrado. Instalando...
    echo.
    python -m pip install --upgrade pip >nul 2>&1
    python -m pip install aiohttp
    if errorlevel 1 (
        echo.
        echo    ERRO ao instalar aiohttp!
        echo    Tente rodar manualmente: pip install aiohttp
        echo.
        pause
        exit /b 1
    )
    echo    OK - aiohttp instalado!
) else (
    echo    OK - aiohttp ja instalado!
)
echo.

:: ============================================================
:: PASSO 3 - Verifica se os arquivos necessarios existem
:: ============================================================
echo [3/5] Verificando arquivos do projeto...

if not exist "server.py" (
    echo    ERRO: Arquivo server.py nao encontrado!
    echo    Coloque este .BAT na mesma pasta do server.py
    pause
    exit /b 1
)

if not exist "index.html" (
    echo    ERRO: Arquivo index.html nao encontrado!
    pause
    exit /b 1
)

if not exist "app.js" (
    echo    ERRO: Arquivo app.js nao encontrado!
    pause
    exit /b 1
)

echo    OK - Todos os arquivos encontrados!
echo.

:: ============================================================
:: PASSO 4 - Verifica se a porta 8080 esta livre
:: ============================================================
echo [4/5] Verificando porta 8080...

netstat -ano | findstr ":8080" >nul 2>&1
if not errorlevel 1 (
    echo.
    echo    AVISO: A porta 8080 ja esta sendo usada!
    echo.
    echo    Isso pode significar que:
    echo    - O servidor ja esta rodando em outra janela
    echo    - Outro programa esta usando essa porta
    echo.
    set /p RESPOSTA="Deseja tentar finalizar processos na porta 8080? (S/N): "
    if /i "%RESPOSTA%"=="S" (
        for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8080"') do (
            taskkill /F /PID %%a >nul 2>&1
        )
        echo    Processos finalizados.
        timeout /t 2 >nul
    ) else (
        echo    Continuando mesmo assim...
    )
)
echo    OK - Porta 8080 pronta!
echo.

:: ============================================================
:: PASSO 5 - Inicia o servidor
:: ============================================================
echo [5/5] Iniciando servidor...
echo.
echo ============================================================
echo    SERVIDOR RODANDO
echo ============================================================
echo.
echo    URL:      http://localhost:8080
echo    WebSocket: ws://localhost:8080/ws
echo.
echo    O navegador vai abrir automaticamente em 3 segundos.
echo.
echo    Pressione CTRL+C nesta janela para PARAR o servidor.
echo.
echo ============================================================
echo.

:: Abre o navegador depois de 3 segundos
start "" cmd /c "timeout /t 3 >nul && start http://localhost:8080"

:: Inicia o servidor (mantem a janela aberta)
python server.py

:: Se o servidor cair, mostra mensagem
echo.
echo ============================================================
echo    SERVIDOR PARADO
echo ============================================================
echo.
echo    O servidor foi encerrado.
echo.
pause