@echo off
setlocal
title Configurar Navegador - Carteira BRN P2P
color 0E
cd /d "%~dp0"

cls
echo.
echo ============================================================
echo    CONFIGURAR NAVEGADOR - Carteira BRN P2P
echo ============================================================
echo.
echo    Selecione qual navegador abrira a carteira:
echo.
echo    [1] Google Chrome  (recomendado)
echo    [2] Microsoft Edge
echo    [3] Navegador padrao do Windows
echo    [4] Digitar caminho manualmente
echo    [0] Cancelar
echo.

set /p OPCAO="   Opcao [0-4]: "

if "%OPCAO%"=="1" goto CHROME
if "%OPCAO%"=="2" goto EDGE
if "%OPCAO%"=="3" goto PADRAO
if "%OPCAO%"=="4" goto MANUAL
if "%OPCAO%"=="0" goto CANCELAR
echo    Opcao invalida.
pause
exit /b 1

:CHROME
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    >navegador.txt echo C:\Program Files\Google\Chrome\Application\chrome.exe
    echo    OK - Chrome configurado.
    goto FIM
)
if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    >navegador.txt echo C:\Program Files (x86)\Google\Chrome\Application\chrome.exe
    echo    OK - Chrome (x86) configurado.
    goto FIM
)
echo    Chrome nao encontrado. Use a opcao 3 ou 4.
pause
exit /b 1

:EDGE
if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" (
    >navegador.txt echo C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe
    echo    OK - Edge configurado.
    goto FIM
)
if exist "C:\Program Files\Microsoft\Edge\Application\msedge.exe" (
    >navegador.txt echo C:\Program Files\Microsoft\Edge\Application\msedge.exe
    echo    OK - Edge configurado.
    goto FIM
)
echo    Edge nao encontrado. Use a opcao 3 ou 4.
pause
exit /b 1

:PADRAO
>navegador.txt echo padrao
echo    OK - Sera usado o navegador padrao do sistema.
goto FIM

:MANUAL
echo.
echo    Cole o caminho completo do .exe do navegador
echo    Exemplo: C:\Program Files\Google\Chrome\Application\chrome.exe
echo.
set /p CAMINHO="   Caminho: "
if "%CAMINHO%"=="" (
    echo    Caminho vazio.
    pause
    exit /b 1
)
if not exist "%CAMINHO%" (
    echo    Arquivo nao encontrado: %CAMINHO%
    pause
    exit /b 1
)
>navegador.txt echo %CAMINHO%
echo    OK - Configurado.
goto FIM

:CANCELAR
echo    Cancelado.
pause
exit /b 1

:FIM
echo.
echo    Arquivo navegador.txt atualizado.
pause
exit /b 0