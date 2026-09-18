@echo off
title AudioLink - Notebook (enviando microfone)
cd /d "%~dp0"

rem Guarda o IP do PC para nao ter que digitar toda vez.
rem Para trocar o IP, apague o arquivo ip_do_pc.txt ou rode:  este.bat --trocar

if "%~1"=="--trocar" del /q ip_do_pc.txt 2>nul

if not exist ip_do_pc.txt goto perguntar
set /p IP=<ip_do_pc.txt
if "%IP%"=="" goto perguntar
goto rodar

:perguntar
echo.
echo  ====================================================
echo   Qual o IP do PC que vai receber o microfone?
echo.
echo   Na rede de casa:  algo como 192.168.0.50
echo   Fora de casa:     o IP do Tailscale, tipo 100.x.x.x
echo.
echo   A janela do PC mostra os IPs dele quando voce roda
echo   o arquivo "2 - PC - RECEBER MICROFONE.bat".
echo  ====================================================
echo.
set /p IP=" IP do PC: "
if "%IP%"=="" (
    echo  Nenhum IP informado.
    pause
    exit /b 1
)
echo %IP%> ip_do_pc.txt

:rodar
echo.
echo  Enviando o microfone deste notebook para %IP%
echo  Deixe esta janela aberta enquanto estiver em ligacao.
echo.
python audiolink.py send --to %IP%

echo.
pause
