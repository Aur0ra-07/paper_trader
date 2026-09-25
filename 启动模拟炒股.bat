@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Paper Trader - 美股模拟交易
python main.py
if errorlevel 1 pause
