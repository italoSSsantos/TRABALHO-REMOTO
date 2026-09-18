@echo off
title AudioLink - PC (recebendo microfone)
cd /d "%~dp0"

echo.
echo  ====================================================
echo   Rode este arquivo NO PC (a maquina que voce acessa
echo   remotamente). Deixe esta janela aberta.
echo.
echo   Depois, no programa de ligacao, escolha
echo   "CABLE Output" como MICROFONE.
echo  ====================================================
echo.

python audiolink.py recv %*

echo.
pause
