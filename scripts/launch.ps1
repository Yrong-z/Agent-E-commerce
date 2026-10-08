# 双击入口薄包装：复用唯一安装、启动锁、进程登记与浏览器去重。
[CmdletBinding()]
param([switch]$NoBrowser,[ValidateSet('Development','Deployment')][string]$Mode='Deployment')
$ErrorActionPreference='Stop'
$LASTEXITCODE=0
& (Join-Path $PSScriptRoot 'dev.ps1') -Action Start -Mode $Mode -OpenBrowser:(-not $NoBrowser)
exit $LASTEXITCODE
