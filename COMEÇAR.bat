@echo off
setlocal enabledelayedexpansion
title Carteira BRN P2P
color 0A
cd /d "%~dp0"

:: ============================================================
:: URL DO NGROK (apenas exibicao; o server.py abre o navegador)
:: ============================================================
set NGROK_URL=https://seventy-rigging-ploy.ngrok-free.dev

cls
echo.
echo ============================================================
echo    CARTEIRA BRN P2P - Iniciando Sistema
echo ============================================================
echo.

:: ============================================================
:: PASSO 1 - VERIFICA SE JA FOI CONFIGURADO O NAVEGADOR
:: ============================================================
if not exist "navegador.txt" (
    echo    Primeira execucao! Configure o navegador primeiro.
    echo.
    pause
    call CONFIGURAR.BAT
    if not exist "navegador.txt" (
        echo    Configuracao cancelada.
        pause
        exit /b 1
    )
)

set "NAVEGADOR="
for /f "usebackq tokens=*" %%n in ("navegador.txt") do set "NAVEGADOR=%%n"
if "!NAVEGADOR!"=="" set "NAVEGADOR=padrao"

echo    Navegador configurado: !NAVEGADOR!
echo.

:: ============================================================
:: PASSO 2 - VERIFICA ARQUIVOS OBRIGATORIOS (.txt)
:: ============================================================
echo [1/2] Verificando arquivos...
if not exist "ngrok_token.txt"  ( echo    ERRO: ngrok_token.txt nao encontrado & pause & exit /b 1 )
if not exist "ngrok_domain.txt" ( echo    ERRO: ngrok_domain.txt nao encontrado & pause & exit /b 1 )
echo    OK
echo.

:: ============================================================
:: PASSO 3 - DECIDE O MODO DE EXECUCAO
::   1) Se CarteiraBRN.exe existir -> usa o .exe (modo compilado)
::   2) Senao, se server.py existir -> usa Python (modo dev)
::   3) Senao -> erro
:: ============================================================
set "MODO="
set "COMANDO="

if exist "CarteiraBRN.exe" (
    set "MODO=EXE"
    set "COMANDO=CarteiraBRN.exe"
    goto VERIFICAR_DEPENDENCIAS
)

if exist "server.py" (
    echo    CarteiraBRN.exe nao encontrado - rodando via Python.
    echo.
    python --version >nul 2>&1
    if errorlevel 1 (
        echo    ERRO: Python nao esta instalado ou nao esta no PATH.
        echo    Instale em https://www.python.org/downloads/
        echo    Ou compile primeiro rodando BUILD.bat.
        pause
        start https://www.python.org/downloads/
        exit /b 1
    )
    set "MODO=PY"
    set "COMANDO=python server.py"

    echo    Verificando dependencias Python...
    python -c "import aiohttp" >nul 2>&1
    if errorlevel 1 (
        echo    Instalando aiohttp...
        python -m pip install aiohttp --quiet
    )
    python -c "import pyngrok" >nul 2>&1
    if errorlevel 1 (
        echo    Instalando pyngrok...
        python -m pip install pyngrok --quiet
    )
    echo    OK
    goto VERIFICAR_DEPENDENCIAS
)

echo    ERRO: nao encontrei CarteiraBRN.exe nem server.py.
echo    Coloque este .bat na pasta do projeto.
pause
exit /b 1

:VERIFICAR_DEPENDENCIAS
echo.
echo [2/2] Iniciando servidor...
echo.
echo ============================================================
echo    SERVIDOR RODANDO
echo ============================================================
echo.
echo    Modo:        !MODO!
echo    Local:       http://localhost:8080
echo    URL Publica: !NGROK_URL!
echo.
echo    O navegador abrira automaticamente quando o tunel responder.
echo.
echo    Para PARAR o servidor: CTRL+C
echo ============================================================
echo.

:: ============================================================
:: PASSO 4 - EXECUTA
:: ============================================================
if "!MODO!"=="EXE" (
    CarteiraBRN.exe
) else (
    python server.py
)

echo.
echo Servidor parado.
pause
exit /b 0