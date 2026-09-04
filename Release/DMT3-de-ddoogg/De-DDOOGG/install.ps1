# De-DDOOGG 一键安装（DMT3 双狗免狗）
# 用法：管理员 PowerShell 执行
#   powershell -ExecutionPolicy Bypass -File install.ps1 [-GameDir D:\DMT3] [-Flavor ir|touch]
#   -Flavor ir    = 红外屏原版（默认）
#   -Flavor touch = 触控屏适配版（启动时会先弹 "Multi Emulator" 窗口，属正常）
param(
    [string]$GameDir = "D:\DMT3",
    [ValidateSet('ir','touch')][string]$Flavor = 'ir'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# 0. 管理员检查
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "请以管理员身份运行！" -ForegroundColor Red; exit 1
}

# 1. 导入测试证书（驱动是测试签名）
Write-Host "[1/6] 导入测试证书 ..."
Get-ChildItem "$root\drivers\*.cer" | ForEach-Object {
    Import-Certificate -FilePath $_.FullName -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
    Import-Certificate -FilePath $_.FullName -CertStoreLocation Cert:\LocalMachine\TrustedPublisher | Out-Null
}

# 2. 测试签名模式
Write-Host "[2/6] 检查 testsigning ..."
$bcd = bcdedit /enum '{current}' | Out-String
if ($bcd -notmatch 'testsigning\s+Yes') {
    bcdedit /set testsigning on | Out-Null
    Write-Host "已开启测试签名模式。**必须重启一次后再运行本脚本继续安装！**" -ForegroundColor Yellow
    exit 2
}

# 3. 安装驱动包
Write-Host "[3/6] 安装驱动包 itoken2 / vrockey6 ..."
# 先移除现有/半残虚拟狗节点（释放对旧驱动包的占用；幂等，不存在无妨），
# 再清仓库旧副本（删不掉=仍被占用，无妨——第 4 步 devcon 始终用包内 INF 安装）。
foreach ($hwid in 'root\vid_0471&pid_485d', 'root\vrockey6') {
    try { & "$root\tools\devcon.exe" remove $hwid 2>$null | Out-Null } catch {}
}
$enum = pnputil /enum-drivers | Out-String
foreach ($b in ($enum -split "(?=oem\d+\.inf)")) {
    if (($b -match 'itoken2\.inf|vrockey6\.inf') -and ($b -match '(oem\d+\.inf)')) {
        Write-Host "  清理旧驱动包 $($Matches[1])"
        try { pnputil /delete-driver $Matches[1] 2>$null | Out-Null } catch {}
    }
}
pnputil /add-driver "$root\drivers\itoken2\itoken2.inf" /install
pnputil /add-driver "$root\drivers\vrockey6\vrockey6.inf" /install

# 4. 创建设备节点（devcon 退出码不可靠——成功也可能非 0，成败以 [6/6] 枚举验证为准）
Write-Host "[4/6] 创建虚拟设备 ..."
foreach ($d in @(@('itoken2\itoken2.inf', 'root\vid_0471&pid_485d'), @('vrockey6\vrockey6.inf', 'root\vrockey6'))) {
    & "$root\tools\devcon.exe" install "$root\drivers\$($d[0])" $d[1]
}
Start-Sleep -Seconds 2

# 5. 部署 multiDLL 到游戏目录
Write-Host "[5/6] 部署 multiDLL 到 $GameDir （版本： $Flavor) ..."
if (-not (Test-Path "$GameDir\Client.exe")) { Write-Host "警告：$GameDir 下没找到 Client.exe，请用 -GameDir 指定游戏目录" -ForegroundColor Yellow }
else {
    # 备份游戏自带的原版 multiDLL.dll（仅首次；默认视为红外屏原版）
    if (-not (Test-Path "$GameDir\multiDLL_orig.dll")) {
        if (Test-Path "$GameDir\multiDLL.dll") { Rename-Item "$GameDir\multiDLL.dll" "multiDLL_orig.dll" }
        else { Copy-Item "$root\multiDLL\multiDLL_orig.dll" "$GameDir\multiDLL_orig.dll" }
    }
    # 两个转发目标都放齐（两个代理各自按名加载，互不干扰）
    Copy-Item "$root\multiDLL\multiDLL_touch.dll" "$GameDir\multiDLL_touch.dll" -Force
    # 按选择部署对应代理
    Copy-Item "$root\multiDLL\proxy_$Flavor.dll" "$GameDir\multiDLL.dll" -Force
    Write-Host "  proxy_$Flavor.dll -> multiDLL.dll 已部署；切版本只需重跑本脚本并换 -Flavor"
}

# 6. 验证
Write-Host "[6/6] 验证 ..."
$devs2 = pnputil /enum-devices | Out-String
$ok1 = $devs2 -match 'Virtual Senselock EL Dongle'
$ok2 = $devs2 -match 'Virtual Rockey6 SMART PLUS Dongle'
Write-Host ("  itoken2v2 (虚拟狗①枚举):  " + $(if ($ok1) {'OK'} else {'缺失!'}))
Write-Host ("  vrockey6  (虚拟狗②):      " + $(if ($ok2) {'OK'} else {'缺失!'}))
if ($ok1 -and $ok2) { Write-Host "`n安装完成！拔掉两只实物狗，直接启动游戏即可。" -ForegroundColor Green }
else {
    Write-Host "`n有设备未就绪，请检查上方输出。" -ForegroundColor Red
    # 自动附 setupapi 日志中的错误行（!!! 前缀 = 安装器错误记录），便于定位驱动安装失败原因
    Write-Host "—— C:\Windows\INF\setupapi.dev.log 最近错误记录 ——" -ForegroundColor Yellow
    try {
        $hit = Get-Content C:\Windows\INF\setupapi.dev.log -Tail 400 -ErrorAction Stop |
            Select-String -Pattern '!!!|vrockey6|itoken2' | Select-Object -Last 12
        if ($hit) { $hit | ForEach-Object { Write-Host ("  " + $_.Line.Trim()) } }
        else { Write-Host '  （未找到相关记录，可手动检查该日志与杀软拦截记录）' }
    } catch { Write-Host "  （读取 setupapi.dev.log 失败：$_）" }
    exit 3
}
