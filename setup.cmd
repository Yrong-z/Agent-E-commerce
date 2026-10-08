@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0" || exit /b 1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dev.ps1" -Action Setup -Mode Deployment
set "TASK_EXIT_CODE=%ERRORLEVEL%"
popd
if not "%TASK_EXIT_CODE%"=="0" echo 配置准备未完成，请按上方具体提示补齐后重试。
pause
exit /b %TASK_EXIT_CODE%
