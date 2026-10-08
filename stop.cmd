@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0" || exit /b 1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\dev.ps1" -Action Stop
set "TASK_EXIT_CODE=%ERRORLEVEL%"
popd
if not "%TASK_EXIT_CODE%"=="0" echo 停止未完成，请查看上方提示；不会强行停止未知进程。
pause
exit /b %TASK_EXIT_CODE%
