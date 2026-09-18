@echo off
title AudioLink - Instalacao
cd /d "%~dp0"

echo.
echo  ====================================================
echo   AudioLink - instalando as dependencias
echo  ====================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo  ERRO: Python nao encontrado.
    echo.
    echo  Instale em https://python.org/downloads
    echo  IMPORTANTE: marque "Add Python to PATH" durante a instalacao.
    echo.
    pause
    exit /b 1
)

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo  ERRO ao instalar. Veja a mensagem acima.
    pause
    exit /b 1
)

echo.
echo  Dependencias instaladas. Verificando os dispositivos de audio...
echo.
python audiolink.py list

echo.
echo  ====================================================
echo   Pronto.
echo.
echo   No PC (o que recebe o microfone) voce ainda precisa
echo   do VB-Cable, se ainda nao apareceu "CABLE Input"
echo   na lista acima:   https://vb-audio.com/Cable/
echo  ====================================================
echo.
pause
