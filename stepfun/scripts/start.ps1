$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot '..')
try {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw '请先安装并启动 Docker Desktop（Linux containers），或按 README 连接现成 seekdb。' }
  npm.cmd ci
  if ($LASTEXITCODE -ne 0) { throw '依赖安装失败' }
  npm.cmd run db:up
  if ($LASTEXITCODE -ne 0) { throw '数据库启动失败，请检查 Docker 日志' }
  npm.cmd run build
  if ($LASTEXITCODE -ne 0) { throw '构建失败' }
  Write-Host '打开 http://localhost:3001'
  npm.cmd start
} finally { Pop-Location }
