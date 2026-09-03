# De-DDOOGG 卸载（移除虚拟狗驱动 + 还原游戏 DLL）
# 用法：管理员 PowerShell 执行  powershell -ExecutionPolicy Bypass -File uninstall.ps1 [-GameDir D:\DMT3]
param(
    [string]$GameDir = "D:\DMT3"
)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]$id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "请以管理员身份运行！" -ForegroundColor Red; exit 1
}

Write-Host "[1/3] 移除虚拟设备 ..."
# 按硬件 ID 移除（幂等，失败无妨）
& "$root\tools\devcon.exe" remove "root\vid_0471&pid_485d" 2>$null | Out-Null
& "$root\tools\devcon.exe" remove "root\vrockey6" 2>$null | Out-Null
# 按设备描述匹配实例再移除（固定实例号如 ROOT\SYSTEM\0003 在别的机器上可能是别的设备，勿用）
$devs = pnputil /enum-devices | Out-String
foreach ($blk in ($devs -split "`r?`n`r?`n")) {
    if ($blk -match 'Virtual Senselock EL Dongle' -or $blk -match 'Virtual Rockey6 SMART PLUS Dongle') {
        if ($blk -match '(?i)(实例 ID|Instance ID)\s*[:：]\s*(\S+)') {
            Write-Host ("  移除 " + $Matches[2])
            pnputil /remove-device "$($Matches[2])" 2>$null | Out-Null
        }
    }
}

Write-Host "[2/3] 删除驱动包 ..."
$enum = pnputil /enum-drivers | Out-String
$blocks = $enum -split "(?=oem\d+\.inf)"
foreach ($b in $blocks) {
    if ($b -match '(oem\d+)\.inf' -and ($b -match 'itoken2\.inf' -or $b -match 'vrockey6\.inf')) {
        $oem = $Matches[1] + '.inf'
        Write-Host "  删除 $oem"
        pnputil /delete-driver $oem /uninstall 2>$null | Out-Null
    }
}

Write-Host "[3/3] 还原游戏 DLL ..."
if (Test-Path "$GameDir\multiDLL_orig.dll") {
    Copy-Item "$GameDir\multiDLL_orig.dll" "$GameDir\multiDLL.dll" -Force
    Remove-Item "$GameDir\multiDLL_touch.dll" -Force -ErrorAction SilentlyContinue
    Write-Host "  已还原 $GameDir\multiDLL.dll（移除触控版转发目标）"
}
Write-Host "完成。（测试签名模式与证书未动；如需关闭：bcdedit /set testsigning off，需重启）" -ForegroundColor Green
