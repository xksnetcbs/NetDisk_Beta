@echo off
cd /d "%~dp0"
node --env-file=.env.local server/gateway.mjs
pause
