@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动本地 HTTPS 服务器（网页版 NFC 写卡）...
python server.py
pause
