@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0" || exit /b 1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1"
set "TASK_EXIT_CODE=%ERRORLEVEL%"
popd
if not "%TASK_EXIT_CODE%"=="0" (
  echo 启动未完成，请查看上方提示。
  pause
)
exit /b %TASK_EXIT_CODE%
