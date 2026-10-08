# 唯一本地安装/进程管理：开发双进程，本地部署单进程；仅监听本机。
[CmdletBinding()]
param(
 [Parameter(Mandatory=$true)][ValidateSet('Setup','Install','Start','Stop','Check','StartEmbedding','StopEmbedding')][string]$Action,
 [ValidateSet('Development','Deployment')][string]$Mode='Development',
 [switch]$SkipDocker,[switch]$OpenBrowser,[string]$PythonPath,[string]$NodePath,[string]$PnpmCli
)
$ErrorActionPreference='Stop'
$env:PYTHONIOENCODING='utf-8'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$OutputEncoding=[Text.UTF8Encoding]::new($false)
$projectRoot=Split-Path -Parent $PSScriptRoot
$runtimeDir=Join-Path $projectRoot '.runtime'
$runtimeFile=Join-Path $runtimeDir 'runtime.json'
$stateFile=Join-Path $runtimeDir 'processes.json'
$browserFile=Join-Path $runtimeDir 'browser-session.json'
$venvPython=Join-Path $projectRoot '.venv\Scripts\python.exe'
New-Item -ItemType Directory -Force -Path $runtimeDir|Out-Null
Set-Location $projectRoot
$hash=[Security.Cryptography.SHA256]::Create()
try{$projectId=[BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($projectRoot.ToLowerInvariant()))).Replace('-','')}finally{$hash.Dispose()}
$mutex=New-Object Threading.Mutex($false,"Local\ShoppingAssistantLaunch_$projectId")
$ownsMutex=$false
function Get-ContentHash {param([string]$Path)
 $stream=[IO.File]::OpenRead((Join-Path $projectRoot $Path)); $digest=[Security.Cryptography.SHA256]::Create()
 try{return [BitConverter]::ToString($digest.ComputeHash($stream)).Replace('-','')}finally{$stream.Dispose();$digest.Dispose()}
}
function Invoke-NativeChecked {param([string]$Executable,[string[]]$Arguments)
 & $Executable @Arguments
 if($LASTEXITCODE -ne 0){throw "命令失败（退出码 $LASTEXITCODE）；检查上方提示后显式重试。"}
}
function Find-Runtime {
 $saved=if(Test-Path $runtimeFile){Get-Content $runtimeFile -Raw|ConvertFrom-Json}else{$null}
 $bundle=Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies'
 if(-not $script:PythonPath){$command=Get-Command python -ErrorAction SilentlyContinue; $script:PythonPath=if($saved){$saved.python}elseif($command){$command.Source}else{Join-Path $bundle 'python\python.exe'}}
 if(-not $script:NodePath){$command=Get-Command node -ErrorAction SilentlyContinue; $script:NodePath=if($saved){$saved.node}elseif($command){$command.Source}else{Join-Path $bundle 'node\bin\node.exe'}}
 if(-not $script:PnpmCli){$script:PnpmCli=if($saved){$saved.pnpm}else{Join-Path $bundle 'node\node_modules\pnpm\bin\pnpm.cjs'}}
 foreach($path in @($script:PythonPath,$script:NodePath,$script:PnpmCli)){if(-not(Test-Path -LiteralPath $path)){throw '运行时缺失，请指定 -PythonPath、-NodePath、-PnpmCli。'}}
 Invoke-NativeChecked $PythonPath @('-c','import sys; assert (3,12)<=sys.version_info[:2]<(3,14)')
 $nodeVersion=& $NodePath --version
 if($LASTEXITCODE -ne 0 -or [version]$nodeVersion.Trim().TrimStart('v') -lt [version]'22.12.0'){throw '需要 Node 22.12 或更新版本。'}
 $pnpmVersion=& $NodePath $PnpmCli --version
 if($LASTEXITCODE -ne 0 -or $pnpmVersion.Trim() -ne '11.19.0'){throw '请使用锁文件对应 pnpm 11.19.0。'}
 $env:PATH="$(Split-Path -Parent $NodePath);$env:PATH"
}
function Install-Dependencies {
 Find-Runtime
 if(-not(Test-Path .env)){Copy-Item .env.example .env; Write-Host '已从样例生成 .env；已有配置不会覆盖。'}
 $pythonReady=$false
 if(Test-Path $venvPython){
  $dependencyCheck="import importlib.metadata as m,re,sys; from pathlib import Path; normalize=lambda n: re.sub(r'[-_.]+','-',n).lower(); installed={normalize(d.metadata['Name']):d.version for d in m.distributions() if d.metadata['Name']}; pairs=[re.fullmatch(r'([\w.-]+)(?:\[.*?\])?==(.+)',s.strip()) for s in Path('api/requirements.lock').read_text().splitlines() if s.strip() and not s.startswith('#')]; sys.exit(0 if all(p and installed.get(normalize(p[1]))==p[2] for p in pairs) and installed.get('shopping-assistant-api')=='0.1.0' else 1)"
  & $venvPython -c $dependencyCheck 2>$null
  $pythonReady=$LASTEXITCODE -eq 0
 }
 if(-not $pythonReady){
  if(-not(Test-Path $venvPython)){Invoke-NativeChecked $PythonPath @('-m','venv','.venv')}
  Invoke-NativeChecked $venvPython @('-m','pip','install','-r','api/requirements.lock')
  Invoke-NativeChecked $venvPython @('-m','pip','install','--no-deps','--no-build-isolation','-e','api')
  Invoke-NativeChecked $venvPython @('-m','pip','check')
 }else{Write-Host 'Python 依赖与锁文件一致，跳过安装。'}
 $installedLock=Join-Path $projectRoot 'web\node_modules\.pnpm\lock.yaml'
 $webReady=(Test-Path 'web/node_modules/vite/bin/vite.js') -and (Test-Path $installedLock) -and ((Get-ContentHash 'web/pnpm-lock.yaml') -eq (Get-ContentHash 'web/node_modules/.pnpm/lock.yaml'))
 $package=Get-Content 'web/package.json' -Raw|ConvertFrom-Json
 foreach($name in @($package.dependencies.PSObject.Properties.Name)+@($package.devDependencies.PSObject.Properties.Name)){if(-not(Test-Path (Join-Path 'web/node_modules' "$name/package.json"))){$webReady=$false}}
 if(-not $webReady){Invoke-NativeChecked $NodePath @($PnpmCli,'--dir','web','install','--frozen-lockfile')}else{Write-Host '前端依赖与锁文件一致，跳过安装。'}
 @{python=$PythonPath;node=$NodePath;pnpm=$PnpmCli}|ConvertTo-Json|Set-Content -Encoding utf8 $runtimeFile
}
function Save-ProcessState {param([object[]]$Items=@()); ConvertTo-Json -InputObject @($Items|Where-Object {$_ -and $_.id})|Set-Content -Encoding utf8 $stateFile}
function Get-RegisteredProcesses {
 if(-not(Test-Path $stateFile)){return @()}
 foreach($item in (Get-Content $stateFile -Raw|ConvertFrom-Json)){if($item -and $item.id){Write-Output $item}}
}
function Test-OwnedProcess {param($Item)
 $process=Get-Process -Id $Item.id -ErrorAction SilentlyContinue
 if(-not $process -or $process.StartTime.ToUniversalTime().Ticks.ToString() -ne $Item.started){return $false}
 $info=Get-CimInstance Win32_Process -Filter "ProcessId=$($Item.id)"
 return $info.CommandLine -and $info.CommandLine.Contains($projectRoot)
}
function Stop-ProcessTree {param([int]$ProcessId)
 foreach($child in @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId")){Stop-ProcessTree $child.ProcessId}
 $process=Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
 if($process){
  try{Stop-Process -Id $ProcessId -Force -ErrorAction Stop}catch{if($_.FullyQualifiedErrorId -notlike '*NoProcessFoundForGivenId*'){throw}}
  if(-not $process.WaitForExit(5000)){throw '已核对的本项目进程未退出，保留登记供恢复。'}
 }
}
function Stop-ProjectProcesses {
 foreach($item in @(Get-RegisteredProcesses)){
  $process=Get-Process -Id $item.id -ErrorAction SilentlyContinue
  if($process -and $process.StartTime.ToUniversalTime().Ticks.ToString() -eq $item.started){if(Test-OwnedProcess $item){Stop-ProcessTree $item.id}else{throw '进程归属不匹配，拒绝停止。'}}
 }
 Save-ProcessState @()
}
function Test-DockerReady {& docker info --format '{{.ServerVersion}}' *> $null; return $LASTEXITCODE -eq 0}
function Ensure-Docker {
 if(-not(Get-Command docker -ErrorAction SilentlyContinue)){throw '未找到 Docker，请安装 Docker Desktop。'}
 if(-not(Test-DockerReady)){
  $desktopExe=Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
  if(-not(Test-Path $desktopExe)){throw 'Docker 引擎未就绪，请手动启动 Docker Desktop。'}
  Write-Host '正在启动 Docker Desktop，等待引擎就绪……'
  if(-not(Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)){Start-Process -FilePath $desktopExe -WindowStyle Hidden|Out-Null}
  $deadline=[DateTime]::UtcNow.AddSeconds(120)
  while(-not(Test-DockerReady)){if([DateTime]::UtcNow -ge $deadline){throw 'Docker 引擎等待超时，请检查 Docker Desktop 后重试。'}; Start-Sleep -Seconds 2}
 }
}
function Assert-DeploymentInputs {
 # 只读核对本项目镜像与端口；不拉镜像、不停止占用端口的未知进程。
 $images=@(& docker compose --profile local-embedding config --images)
 if($LASTEXITCODE -ne 0){throw 'Compose 配置无效，请检查根目录 .env 与 compose.yaml。'}
 foreach($image in $images){
  & docker image inspect --format '{{.Id}}' $image *> $null
  if($LASTEXITCODE -ne 0){throw "本地镜像缺失：$image；请按 README 手动准备镜像后重试，不自动下载。"}
 }
 $ownedIds=[Collections.Generic.HashSet[int]]::new()
 $queue=[Collections.Generic.Queue[int]]::new()
 foreach($item in @(Get-RegisteredProcesses)){if(Test-OwnedProcess $item){$queue.Enqueue([int]$item.id)}}
 while($queue.Count){$current=$queue.Dequeue(); if($ownedIds.Add($current)){foreach($child in @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$current")){$queue.Enqueue([int]$child.ProcessId)}}}
 $ports=if($Mode -eq 'Deployment'){@(8000)}else{@(8000,5173)}
 foreach($port in $ports){foreach($listener in @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)){if(-not $ownedIds.Contains([int]$listener.OwningProcess)){throw "端口 $port 被占用；不会停止未知进程。"}}}
 foreach($service in @('db','embedding')){
  $portName=if($service -eq 'db'){'POSTGRES_PORT'}else{'EMBEDDING_PORT'}
  $fallback=if($service -eq 'db'){5433}else{8082}
  $port=& $venvPython -c "from dotenv import dotenv_values; print(int(dotenv_values('.env').get('$portName') or $fallback))"
  if($LASTEXITCODE -ne 0 -or [int]$port -lt 1 -or [int]$port -gt 65535){throw "$portName 配置无效，需要1至65535的端口。"}
  $running=@(& docker compose ps --status running -q $service)
  if($LASTEXITCODE -ne 0){throw "无法查询本项目 $service。"}
  if(Get-NetTCPConnection -State Listen -LocalPort ([int]$port) -ErrorAction SilentlyContinue){
   $published=$false
   foreach($container in $running){
    $bindings=& docker inspect --format '{{json .NetworkSettings.Ports}}' $container
    if($LASTEXITCODE -ne 0){throw "无法核对本项目 $service 的端口归属。"}
    foreach($binding in ($bindings|ConvertFrom-Json).PSObject.Properties){foreach($hostBinding in $binding.Value){if([int]$hostBinding.HostPort -eq [int]$port){$published=$true}}}
   }
   if(-not $published){throw "端口 $port 已占用，归属不匹配本项目 $service；不会停止未知进程。"}
  }
 }
}
function Confirm-ProjectStopped {
 # 核对停止结果；未知占用只报告，不按端口结束进程。
 $listeners=@(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue|Where-Object {$_.LocalPort -in @(8000,5173)})
 $running=@(& docker compose ps --status running -q db embedding)
 if($LASTEXITCODE -ne 0){throw '无法核对本项目容器停止结果。'}
 if(@(Get-RegisteredProcesses).Count -or $running.Count){throw '本项目仍有运行登记或容器，请检查 .runtime 日志后重试 stop.cmd。'}
 if($listeners.Count){throw ('本项目停止后端口仍被占用，未结束未知进程：'+(($listeners|ForEach-Object {"$($_.LocalPort) / PID $($_.OwningProcess)"}) -join ', '))}
 Write-Host '本项目应用进程已退出，8000/5173 端口已释放，db/embedding 已停止；数据卷、配置和模型保留。'
}
function Start-Embedding {
 Invoke-NativeChecked $venvPython @('-m','scripts.prepare_local','--preflight')
 $port=& $venvPython -c "from dotenv import dotenv_values; print(int(dotenv_values('.env').get('EMBEDDING_PORT') or 8082))"
 if($LASTEXITCODE -ne 0){throw 'EMBEDDING_PORT 配置无效。'}
 $running=& docker compose ps --status running -q embedding
 if($LASTEXITCODE -ne 0){throw '无法查询本项目 embedding。'}
 if((Get-NetTCPConnection -State Listen -LocalPort ([int]$port) -ErrorAction SilentlyContinue) -and -not $running){throw "端口 $port 已占用，不会停止未知进程。"}
 Invoke-NativeChecked 'docker' @('compose','up','-d','--no-deps','--pull','never','--wait','--wait-timeout','120','embedding')
}
function Build-Frontend {
 $files=@(Get-ChildItem 'web/src','web/public' -Recurse -File)+@(Get-Item 'web/index.html','web/package.json','web/pnpm-lock.yaml','web/vite.config.ts','web/tsconfig.json')
 $signature=($files|Sort-Object FullName|ForEach-Object {"$($_.FullName):$(Get-ContentHash $_.FullName.Substring($projectRoot.Length+1))"}) -join '|'
 $buildFile=Join-Path $runtimeDir 'frontend-build.txt'
 if((Test-Path 'web/dist/index.html') -and (Test-Path $buildFile) -and (Get-Content $buildFile -Raw).Trim() -eq $signature){Write-Host '生产构建未变化，复用已有产物。'; return}
 Invoke-NativeChecked $NodePath @($PnpmCli,'--dir','web','run','typecheck')
 Invoke-NativeChecked $NodePath @($PnpmCli,'--dir','web','run','build')
 Set-Content -Encoding utf8 $buildFile $signature
}
function Test-AppReady {param([string]$Url)
 try{$health=Invoke-RestMethod "$Url/api/health" -TimeoutSec 3; $page=Invoke-WebRequest $Url -UseBasicParsing -TimeoutSec 3; return $health.status -eq 'ok' -and $page.StatusCode -eq 200 -and $page.Content.Contains('<div id="root">')}catch{return $false}
}
function Start-App {
 $url=if($Mode -eq 'Deployment'){'http://127.0.0.1:8000'}else{'http://127.0.0.1:5173'}
 $configHash=Get-ContentHash '.env'
 $items=@(Get-RegisteredProcesses)
 $required=if($Mode -eq 'Deployment'){@('api')}else{@('api','web')}
 $reusable=$items.Count -eq $required.Count
 foreach($name in $required){$matches=@($items|Where-Object {$_.name -eq $name}); if($matches.Count -ne 1 -or -not(Test-OwnedProcess $matches[0]) -or $matches[0].mode -ne $Mode -or $matches[0].config_hash -ne $configHash){$reusable=$false}}
 if($reusable -and (Test-AppReady $url)){Write-Host '应用已运行，复用现有进程。'}else{
  Stop-ProjectProcesses
  $ports=if($Mode -eq 'Deployment'){@(8000)}else{@(8000,5173)}
  foreach($port in $ports){if(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue){throw "端口 $port 被占用；不会停止未知进程。"}}
  $items=@(); $apiDir=Join-Path $projectRoot 'api'; $previousServe=$env:SERVE_FRONTEND
  try{
   $env:SERVE_FRONTEND=if($Mode -eq 'Deployment'){'true'}else{'false'}
   $process=Start-Process -FilePath $venvPython -ArgumentList @('-m','uvicorn','app.main:app','--app-dir',('"{0}"' -f $apiDir),'--loop','app.db:create_event_loop','--host','127.0.0.1','--port','8000') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'api.log') -RedirectStandardError (Join-Path $runtimeDir 'api-error.log') -PassThru
  }finally{$env:SERVE_FRONTEND=$previousServe}
  $items+=@{id=$process.Id;started=$process.StartTime.ToUniversalTime().Ticks.ToString();name='api';mode=$Mode;config_hash=$configHash}; Save-ProcessState $items
  if($Mode -eq 'Development'){
   $vite=Join-Path $projectRoot 'web\node_modules\vite\bin\vite.js'
   $process=Start-Process -FilePath $NodePath -ArgumentList @(('"{0}"' -f $vite),'--host','127.0.0.1','--port','5173','--strictPort') -WorkingDirectory (Join-Path $projectRoot 'web') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'web.log') -RedirectStandardError (Join-Path $runtimeDir 'web-error.log') -PassThru
   $items+=@{id=$process.Id;started=$process.StartTime.ToUniversalTime().Ticks.ToString();name='web';mode=$Mode;config_hash=$configHash}; Save-ProcessState $items
  }
  $ready=$false
  for($attempt=0;$attempt -lt 30;$attempt++){if(Test-AppReady $url){$ready=$true;break}; Start-Sleep -Milliseconds 500}
  if(-not $ready){throw '应用未就绪；已登记进程保留供诊断，请查看 .runtime 日志，再执行 Stop 后重试。'}
 }
 $session=($items|Sort-Object name|ForEach-Object {"$($_.name):$($_.id):$($_.started)"}) -join '|'
 if($OpenBrowser){
  $opened=if(Test-Path $browserFile){Get-Content $browserFile -Raw|ConvertFrom-Json}else{$null}
  if(-not $opened -or $opened.session -ne $session){$browserProcess=Start-Process $url -PassThru; @{session=$session;opened_at=[DateTime]::UtcNow.ToString('o');url=$url;browser_process_id=if($browserProcess){$browserProcess.Id}else{$null}}|ConvertTo-Json|Set-Content -Encoding utf8 $browserFile; Write-Host '已打开浏览器。'}else{Write-Host '本次运行已自动打开过浏览器，不重复打开。'}
 }
 Write-Host "就绪：$url （$Mode）  API 文档：http://127.0.0.1:8000/docs"
}
try{
 try{$ownsMutex=$mutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{$ownsMutex=$true}
 if(-not $ownsMutex){Write-Host '已有启停任务正在执行，忽略重复点击。'; return}
 switch($Action){
  'Setup' {
   Install-Dependencies
   Invoke-NativeChecked $venvPython @('-m','scripts.prepare_local','--preflight','--require-chat')
   Ensure-Docker
   Assert-DeploymentInputs
   Build-Frontend
   Write-Host '本地部署准备完成；未启动业务服务或写入数据。下一步双击 start.cmd。'
  }
  'Install' {Install-Dependencies; Write-Host '依赖就绪；配置与模型准备完成后可启动。'}
  'Start' {
   Install-Dependencies
   Invoke-NativeChecked $venvPython @('-m','scripts.prepare_local','--preflight')
   if(-not $SkipDocker){Ensure-Docker; Assert-DeploymentInputs; Invoke-NativeChecked 'docker' @('compose','up','-d','--wait','--wait-timeout','120','--pull','never','db'); Start-Embedding}
   Invoke-NativeChecked $venvPython @('-m','scripts.prepare_local')
   if($Mode -eq 'Deployment'){Build-Frontend}
   Start-App
  }
  'Stop' {Stop-ProjectProcesses; Invoke-NativeChecked 'docker' @('compose','stop','db','embedding'); Confirm-ProjectStopped}
  'StartEmbedding' {if(-not(Test-Path $venvPython)){throw '请先执行 Install。'}; Ensure-Docker; Start-Embedding}
  'StopEmbedding' {Invoke-NativeChecked 'docker' @('compose','stop','embedding')}
  'Check' {Push-Location api; try{Invoke-NativeChecked $venvPython @('-m','scripts.check_framework')}finally{Pop-Location}}
 }
}catch{
 Write-Host '操作未完成；已启动服务不会被误报为成功。配置缺项请编辑根目录 .env（可运行 notepad .env），再双击 setup.cmd；启停失败请检查 .runtime 日志，双击 stop.cmd 后重试 start.cmd；数据库卷保留。'
 Write-Host ('本项目后台进程登记：'+((@(Get-RegisteredProcesses)|ForEach-Object {"$($_.name):$($_.id)"}) -join ', '))
 if(Get-Command docker -ErrorAction SilentlyContinue){& docker compose ps --format '{{.Service}}: {{.State}}' 2>$null}
 throw
}finally{if($ownsMutex){$mutex.ReleaseMutex()}; $mutex.Dispose()}
