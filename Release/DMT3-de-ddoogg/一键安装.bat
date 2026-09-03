@echo off
rem ============================================================
rem  DMT3 De-DDOOGG one-click installer (GUI + CLI)
rem  Kimi K3 & AnderX
rem  License: CC BY-NC-SA 4.0 (see De-DDOOGG)
rem ============================================================
setlocal
set "DMT3_SELF=%~f0"
set "DMT3_RAWARGS=%*"
set "DMT3_WS=-WindowStyle Normal"
if "%~1"=="" set "DMT3_WS=-WindowStyle Hidden"
powershell -STA -NoProfile -ExecutionPolicy Bypass %DMT3_WS% -Command "$c=[IO.File]::ReadAllText($env:DMT3_SELF,[Text.Encoding]::UTF8); iex $c.Substring($c.LastIndexOf('#__PS_BEGIN__'))"
exit /b %ERRORLEVEL%
#__PS_BEGIN__
# DMT3 De-DDOOGG 一键安装器 — PowerShell 段
# 双击 = 图形界面。命令行：
#   一键安装.bat status [游戏目录]
#   一键安装.bat install [游戏目录] [ir|touch] [launcher] [nodgv]   全自动部署（UAC 提权）
#   一键安装.bat uninstall [游戏目录]                               卸载（UAC 提权）
#   一键安装.bat deploy-files [游戏目录] [launcher] [nodgv]         仅部署文件层（不动驱动，无需管理员）
#   一键安装.bat restore-files [游戏目录]                           仅还原文件层（无需管理员）
#   一键安装.bat testmode-on | testmode-off                         进/出测试模式（3 秒警告 + UAC）
$ErrorActionPreference = 'Stop'
$script:RootDir = Split-Path -Parent $env:DMT3_SELF
$script:PkgDir  = Join-Path $script:RootDir 'De-DDOOGG'

$global:__cliArgs = @()
if ($env:DMT3_RAWARGS) {
    [regex]::Matches($env:DMT3_RAWARGS, '"[^"]*"|\S+') | ForEach-Object {
        $global:__cliArgs += $_.Value.Trim('"')
    }
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ------------------------------------------------------------ 文件层 ----

$script:StartKitFiles = @('CRT_R1.dll', 'hid.dll', 'CardNum.txt')
$script:DgvFiles = @('D3D8.dll', 'D3D9.dll', 'D3DImm.dll', 'DDraw.dll', 'dgVoodoo.conf')
$script:LauncherFiles = @('launcher.exe', 'libver.dll', 'LauncherSettings.ini', 'launcher.dat')

# 覆盖前把原版改名为 <名>.bak_official（幂等）
function Backup-Then-Copy {
    param([string]$SrcFile, [string]$DstDir, [string]$Name, [scriptblock]$Log)
    $dst = Join-Path $DstDir $Name
    if ((Test-Path $dst) -and -not (Test-Path "$dst.bak_official")) {
        Rename-Item -LiteralPath $dst -NewName "$Name.bak_official"
        & $Log "  备份 $Name -> $Name.bak_official"
    }
    Copy-Item $SrcFile $dst -Force
    & $Log "  部署 $Name"
}

function Copy-DirMerge {
    param([string]$SrcDir, [string]$DstDir, [scriptblock]$Log)
    Copy-Item $SrcDir $DstDir -Recurse -Force
    $n = (Get-ChildItem $DstDir -Recurse -File).Count
    & $Log "  部署 $(Split-Path $SrcDir -Leaf)\（$n 个文件）"
}

# 文件层部署：StartKit + RCGrandDogW32 stub（+ 可选 Launcher / dgVoodoo2）
function Deploy-Files {
    param([string]$GameDir, [bool]$WithLauncher, [bool]$WithDgv, [scriptblock]$Log)
    if (-not (Test-Path (Join-Path $GameDir 'Client.exe'))) {
        & $Log "!! $GameDir 下没有 Client.exe，跳过文件部署"
        return $false
    }
    $sk = Join-Path $script:RootDir 'StartKit'
    & $Log "[文件] StartKit（pakkey / CRT_R1 读卡器模拟 / hid.dll / CardNum / Resource 覆盖层）"
    foreach ($f in $script:StartKitFiles) { Backup-Then-Copy (Join-Path $sk $f) $GameDir $f $Log }
    Copy-DirMerge (Join-Path $sk 'pakkey') (Join-Path $GameDir 'pakkey') $Log
    Copy-DirMerge (Join-Path $sk 'Resource') (Join-Path $GameDir 'Resource') $Log

    # RCGrandDogW32 stub
    & $Log '[文件] RCGrandDogW32.dll stub'
    Backup-Then-Copy (Join-Path $script:PkgDir 'multiDLL\RCGrandDogW32_stub.dll') $GameDir 'RCGrandDogW32.dll' $Log

    if ($WithDgv) {
        & $Log '[文件] dgVoodoo2（Win11 显示修复）'
        foreach ($f in $script:DgvFiles) { Backup-Then-Copy (Join-Path $script:RootDir "dgVoodoo2\$f") $GameDir $f $Log }
    }
    if ($WithLauncher) {
        & $Log '[文件] Launcher 2.01'
        foreach ($f in $script:LauncherFiles) { Backup-Then-Copy (Join-Path $script:RootDir "Launcher\$f") $GameDir $f $Log }
    }
    return $true
}

# 文件层还原：恢复所有 .bak_official，删除我们加的文件
function Restore-Files {
    param([string]$GameDir, [scriptblock]$Log)
    $restored = 0
    Get-ChildItem $GameDir -File -Filter '*.bak_official' -ErrorAction SilentlyContinue | ForEach-Object {
        $orig = $_.Name -replace '\.bak_official$', ''
        $target = Join-Path $GameDir $orig
        if (Test-Path $target) { Remove-Item $target -Force }
        Rename-Item -LiteralPath $_.FullName -NewName $orig
        & $Log "  还原 $orig"
        $restored++
    }
    foreach ($f in @('hid.dll', 'CardNum.txt') + $script:DgvFiles) {
        $p = Join-Path $GameDir $f
        if (Test-Path $p) { Remove-Item $p -Force; & $Log "  移除 $f" }
    }
    & $Log "文件层还原完成（还原 $restored 个原版备份）。pakkey\ 与 Resource\ 为新增目录，官方组件下不生效，保留无害，可手动删除。"
}

# ------------------------------------------------------------ 系统层 ----

function Invoke-PkgScript {
    param([string]$Script, [string[]]$ExtraArgs)
    $ps1 = Join-Path $script:PkgDir $Script
    if (-not (Test-Path $ps1)) { throw "找不到 $ps1（本安装器应放在套装根目录）" }
    & powershell -NoProfile -ExecutionPolicy Bypass -File $ps1 @ExtraArgs
}

function Invoke-Elevated {
    param([string[]]$BatArgs)
    # 直接以 UAC 提升启动本 bat（ShellExecute runas；不再走 cmd /k 拼接——那会因引号断掉）
    # 末尾加 'pause' 哨兵：CLI 跑完后停住供查看
    Start-Process -Verb RunAs -WorkingDirectory $script:RootDir `
        -FilePath $env:DMT3_SELF -ArgumentList ($BatArgs + 'pause')
}

# 一键安装全流程（需管理员）：文件层 → De-DDOOGG install.ps1（证书/驱动/代理）
function Invoke-FullInstall {
    param([string]$GameDir, [string]$Flavor, [bool]$WithLauncher, [bool]$WithDgv, [scriptblock]$Log)
    if (-not (Deploy-Files -GameDir $GameDir -WithLauncher $WithLauncher -WithDgv $WithDgv -Log $Log)) { return }
    & $Log "[系统] 驱动/证书/代理（install.ps1 -Flavor $Flavor）……"
    Invoke-PkgScript 'install.ps1' @('-GameDir', $GameDir, '-Flavor', $Flavor) |
        ForEach-Object { & $Log "$ $_" }
    & $Log '全部完成。若 testsigning 是本次才开启的，请重启一次电脑。'
}

# 一键卸载全流程（需管理员）：De-DDOOGG uninstall.ps1 → 文件层还原
function Invoke-FullUninstall {
    param([string]$GameDir, [scriptblock]$Log)
    & $Log '[系统] 卸载虚拟狗驱动（uninstall.ps1）……'
    Invoke-PkgScript 'uninstall.ps1' @('-GameDir', $GameDir) |
        ForEach-Object { & $Log "$ $_" }
    & $Log '[文件] 还原文件层……'
    Restore-Files -GameDir $GameDir -Log $Log
    & $Log '卸载完成。'
}

# ---------------------------------------------------------- 测试模式 ----

function Show-TestmodeWarning {
    param([bool]$Entering)
    $f = New-Object System.Windows.Forms.Form
    $f.Text = '风险警告'
    $f.Width = 560
    $f.Height = 300
    $f.StartPosition = 'CenterScreen'
    $f.TopMost = $true
    $f.FormBorderStyle = 'FixedDialog'
    $f.MaximizeBox = $false
    $f.MinimizeBox = $false
    $msg = New-Object System.Windows.Forms.Label
    if ($Entering) {
        $msg.Text = "即将进入测试模式（bcdedit /set testsigning on）：`r`n`r`n" +
                    "· 桌面右下角会出现「测试模式」水印`r`n" +
                    "· 系统驱动加载门槛降低：任何测试签名的驱动都能加载`r`n" +
                    "  （本套装的虚拟狗驱动依赖它；这也是 Windows 的固有安全权衡）`r`n" +
                    "· 需重启电脑后才生效`r`n`r`n确定键将在 3 秒后可用，请确认你了解此风险。"
    } else {
        $msg.Text = "即将退出测试模式（bcdedit /set testsigning off）：`r`n`r`n" +
                    "· 重启后虚拟狗驱动将无法加载，游戏必须插回两只实物狗才能运行`r`n" +
                    "· 桌面「测试模式」水印消失`r`n" +
                    "· 需重启电脑后才生效`r`n`r`n确定键将在 3 秒后可用，请确认你了解此后果。"
    }
    $msg.SetBounds(15, 10, 520, 170)
    $msg.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 9)
    $btnOK = New-Object System.Windows.Forms.Button
    $btnOK.Text = '确定（3）'
    $btnOK.Enabled = $false
    $btnOK.SetBounds(160, 195, 110, 32)
    $btnCancel = New-Object System.Windows.Forms.Button
    $btnCancel.Text = '取消'
    $btnCancel.SetBounds(290, 195, 110, 32)
    $f.Controls.Add($msg)
    $f.Controls.Add($btnOK)
    $f.Controls.Add($btnCancel)
    $f.CancelButton = $btnCancel
    $script:tmCount = 3
    $timer = New-Object System.Windows.Forms.Timer
    $timer.Interval = 1000
    $timer.add_Tick({
        $script:tmCount--
        if ($script:tmCount -le 0) {
            $timer.Stop()
            $btnOK.Enabled = $true
            $btnOK.Text = '确定'
        } else {
            $btnOK.Text = "确定（$script:tmCount）"
        }
    })
    $timer.Start()
    $btnOK.add_Click({ $f.DialogResult = [System.Windows.Forms.DialogResult]::OK; $f.Close() })
    $btnCancel.add_Click({ $f.DialogResult = [System.Windows.Forms.DialogResult]::Cancel; $f.Close() })
    $r = $f.ShowDialog()
    $timer.Dispose()
    $f.Dispose()
    return ($r -eq [System.Windows.Forms.DialogResult]::OK)
}

function Set-Testmode {
    param([bool]$On)
    if ($On) { bcdedit /set testsigning on | Out-Host } else { bcdedit /set testsigning off | Out-Host }
    return ($LASTEXITCODE -eq 0)
}

function Invoke-Testmode {
    param([bool]$On, [bool]$SkipWarning)
    $action = if ($On) { 'testmode-on' } else { 'testmode-off' }
    if (-not $SkipWarning) {
        if (-not (Show-TestmodeWarning $On)) { return $false }
    }
    if (-not (Test-Admin)) {
        Write-Host '需要管理员权限，正在通过 UAC 提权……'
        Invoke-Elevated -BatArgs @($action, 'force')
        return $true
    }
    $okv = Set-Testmode $On
    if ($okv) {
        if ($On) {
            Write-Host '已开启测试模式。**重启电脑后生效**（桌面将出现「测试模式」水印）。'
        } else {
            Write-Host '已关闭测试模式。**重启电脑后生效**（虚拟狗将不能加载，游戏需插回实物狗）。'
        }
    } else {
        Write-Host 'bcdedit 执行失败。'
    }
    return $okv
}

# ------------------------------------------------------------ 状态检查 ----

function Get-DdgStatus {
    param([string]$GameDir)
    $L = New-Object System.Collections.Generic.List[string]
    $bcd = ''
    try { $bcd = (bcdedit /enum '{current}' 2>$null | Out-String) } catch {}
    if (-not $bcd.Trim()) {
        try { $bcd = (bcdedit /enum active 2>$null | Out-String) } catch {}
    }
    if ($bcd -match 'testsigning\s+Yes') {
        $ts = '开'
    } elseif ($bcd -match 'testsigning') {
        $ts = '关（驱动需要它开启；install 会自动开，需重启生效）'
    } else {
        $ts = '无法读取（非管理员看不到 BCD）。若桌面右下角有「测试模式」水印即已开启'
    }
    $L.Add("测试签名模式 testsigning: $ts")
    # cert（按包内 .cer 的指纹检测是否已导入，兼容证书改名）
    $cerFile = Get-ChildItem (Join-Path $script:PkgDir 'drivers') -Filter '*.cer' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cerFile) {
        $bundleCert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($cerFile.FullName)
        $found = Get-ChildItem Cert:\LocalMachine\Root -ErrorAction SilentlyContinue | Where-Object { $_.Thumbprint -eq $bundleCert.Thumbprint }
        $L.Add("测试证书 " + $bundleCert.GetNameInfo('SimpleName', $false) + ": " + $(if ($found) { "已导入（到期 $($bundleCert.NotAfter.ToString('yyyy-MM-dd'))）" } else { '未导入' }))
    } else {
        $L.Add('测试证书: 包内未找到 .cer 文件')
    }
    foreach ($svc in 'itoken2v2', 'vrockey6') {
        $s = Get-Service $svc -ErrorAction SilentlyContinue
        $L.Add("驱动服务 $svc : " + $(if ($s) { $s.Status } else { '未安装' }))
    }
    $devs = (pnputil /enum-devices 2>$null | Out-String)
    $L.Add("虚拟狗① (Virtual Senselock EL Dongle): " + $(if ($devs -match 'Virtual Senselock EL Dongle') { '在线' } else { '不存在' }))
    $L.Add("虚拟狗② (Virtual Rockey6 SMART PLUS Dongle): " + $(if ($devs -match 'Virtual Rockey6 SMART PLUS Dongle') { '在线' } else { '不存在' }))
    $L.Add('—')
    $L.Add("游戏目录: $GameDir")
    if (-not (Test-Path (Join-Path $GameDir 'Client.exe'))) {
        $L.Add('  !! 该目录下没有 Client.exe')
    } else {
        $L.Add('  Client.exe: 存在')
        $md = Join-Path $GameDir 'multiDLL.dll'
        if (Test-Path $md) {
            $len = (Get-Item $md).Length
            $L.Add("  multiDLL.dll: $len 字节 " + $(if ($len -eq 439296) { '（= 免狗代理，已部署）' } elseif ($len -eq 24576) { '（官方红外原版，未部署代理）' } else { '（未知版本）' }))
        }
        foreach ($f in 'multiDLL_orig.dll', 'multiDLL_touch.dll', 'hid.dll') {
            $L.Add("  ${f}: " + $(if (Test-Path (Join-Path $GameDir $f)) { '在' } else { '缺' }))
        }
        $rc = Join-Path $GameDir 'RCGrandDogW32.dll'
        if (Test-Path $rc) {
            $len = (Get-Item $rc).Length
            $L.Add("  RCGrandDogW32.dll: $len 字节 " + $(if ($len -eq 6144) { '（= stub，已部署）' } elseif ($len -eq 69632) { '（官方原版，未替换 stub）' } else { '（未知版本）' }))
        }
        $L.Add("  pakkey\: " + $(if (Test-Path (Join-Path $GameDir 'pakkey')) { '在（StartKit 已部署）' } else { '缺（StartKit 未部署）' }))
        $L.Add("  CRT_R1.dll: " + $(if ((Test-Path (Join-Path $GameDir 'CRT_R1.dll')) -and ((Get-Item (Join-Path $GameDir 'CRT_R1.dll')).Length -eq 190976)) { '读卡器模拟器版（StartKit）' } else { '官方版（未替换）' }))
        $L.Add("  dgVoodoo2: " + $(if (Test-Path (Join-Path $GameDir 'D3D9.dll')) { '已部署' } else { '未部署' }))
    }
    return $L
}

# ---------------------------------------------------------------- CLI ----
if ($global:__cliArgs.Count -gt 0) {
    Write-Host '本程序开源、免费。如果您是付费得到这个程序的，请立即退款并举报卖家。'
    Write-Host ''
    $act = $global:__cliArgs[0].ToLower()
    $rest = @($global:__cliArgs | Select-Object -Skip 1)
    $gameDir = 'D:\DMT3'
    $flavor = 'ir'
    $withLauncher = $false
    $withDgv = $true
    foreach ($a in $rest) {
        $al = $a.ToLower()
        if ($al -in 'ir', 'touch') { $flavor = $al }
        elseif ($al -eq 'launcher') { $withLauncher = $true }
        elseif ($al -eq 'nodgv') { $withDgv = $false }
        elseif ($al -eq 'force') { }
        elseif ($al -eq 'pause') { $script:wantPause = $true }
        elseif (Test-Path $a -ErrorAction SilentlyContinue) { $gameDir = $a }
        elseif ($a -match '^[A-Za-z]:') { $gameDir = $a }
    }
    switch ($act) {
        'status' {
            Get-DdgStatus -GameDir $gameDir | ForEach-Object { Write-Host $_ }
            break
        }
        'install' {
            if (-not (Test-Admin)) {
                Write-Host '需要管理员权限，正在通过 UAC 提权……'
                $ea = @('install', $gameDir, $flavor)
                if ($withLauncher) { $ea += 'launcher' }
                if (-not $withDgv) { $ea += 'nodgv' }
                Invoke-Elevated -BatArgs $ea
                break
            }
            Invoke-FullInstall -GameDir $gameDir -Flavor $flavor -WithLauncher $withLauncher -WithDgv $withDgv -Log { param($s) Write-Host $s }.GetNewClosure()
            break
        }
        'uninstall' {
            if (-not (Test-Admin)) {
                Write-Host '需要管理员权限，正在通过 UAC 提权……'
                Invoke-Elevated -BatArgs @('uninstall', $gameDir)
                break
            }
            Invoke-FullUninstall -GameDir $gameDir -Log { param($s) Write-Host $s }.GetNewClosure()
            break
        }
        'deploy-files' {
            [void](Deploy-Files -GameDir $gameDir -WithLauncher $withLauncher -WithDgv $withDgv -Log { param($s) Write-Host $s }.GetNewClosure())
            break
        }
        'restore-files' {
            Restore-Files -GameDir $gameDir -Log { param($s) Write-Host $s }.GetNewClosure()
            break
        }
        { $_ -in 'testmode-on', 'testmode-off' } {
            $on = ($act -eq 'testmode-on')
            $skip = $rest -contains 'force'
            Invoke-Testmode -On $on -SkipWarning $skip
            break
        }
        default {
            Write-Host '用法: 一键安装.bat status|install|uninstall|deploy-files|restore-files|testmode-on|testmode-off [游戏目录] [ir|touch] [launcher] [nodgv]'
            Write-Host '  不带参数双击 = 图形界面'
            exit 2
        }
    }
    if ($script:wantPause) { [void](Read-Host '---- 结束，回车关闭 ----') }
    exit 0
}

# ---------------------------------------------------------------- GUI ----
$form = New-Object System.Windows.Forms.Form
$form.Text = 'DMT3 De-DDOOGG 一键安装器' + $(if (Test-Admin) { '（管理员）' } else { '（非管理员：安装/卸载时会请求 UAC 提权）' })
$form.Width = 720
$form.Height = 640
$form.StartPosition = 'CenterScreen'
$form.TopMost = $true
$form.add_Shown({ $form.TopMost = $false; $form.Activate() })

$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = '游戏目录（含 Client.exe）：'
$lbl.AutoSize = $true
$lbl.Location = New-Object System.Drawing.Point(10, 13)

$txtDir = New-Object System.Windows.Forms.TextBox
$txtDir.SetBounds(185, 10, 405, 24)
$txtDir.Anchor = 'Left', 'Right', 'Top'
$txtDir.Text = $(if (Test-Path 'D:\DMT3\Client.exe') { 'D:\DMT3' } else { '' })

$btnBrowse = New-Object System.Windows.Forms.Button
$btnBrowse.Text = '浏览...'
$btnBrowse.SetBounds(598, 9, 90, 26)
$btnBrowse.Anchor = 'Right', 'Top'
$btnBrowse.add_Click({
    $d = New-Object System.Windows.Forms.FolderBrowserDialog
    if ($txtDir.Text) { $d.SelectedPath = $txtDir.Text }
    if ($d.ShowDialog($form) -eq 'OK') { $txtDir.Text = $d.SelectedPath }
})

$grp = New-Object System.Windows.Forms.GroupBox
$grp.Text = '代理版本（屏幕适配）'
$grp.SetBounds(10, 42, 678, 52)
$grp.Anchor = 'Left', 'Right', 'Top'
$rbIr = New-Object System.Windows.Forms.RadioButton
$rbIr.Text = '原版红外屏适配'
$rbIr.SetBounds(12, 20, 320, 22)
$rbIr.Checked = $true
$rbTouch = New-Object System.Windows.Forms.RadioButton
$rbTouch.Text = '原版红外屏之外触摸屏选这个'
$rbTouch.SetBounds(340, 20, 330, 22)
$grp.Controls.Add($rbIr)
$grp.Controls.Add($rbTouch)

$grpC = New-Object System.Windows.Forms.GroupBox
$grpC.Text = '组件（一键安装会自动部署）'
$grpC.SetBounds(10, 100, 678, 52)
$grpC.Anchor = 'Left', 'Right', 'Top'
$ckStart = New-Object System.Windows.Forms.CheckBox
$ckStart.Text = 'StartKit（pakkey/读卡器模拟，必选）'
$ckStart.SetBounds(12, 20, 290, 22)
$ckStart.Checked = $true
$ckStart.Enabled = $false
$ckDgv = New-Object System.Windows.Forms.CheckBox
$ckDgv.Text = 'dgVoodoo2（Win11 显示修复）'
$ckDgv.SetBounds(310, 20, 200, 22)
$ckDgv.Checked = $true
$ckLauncher = New-Object System.Windows.Forms.CheckBox
$ckLauncher.Text = 'Launcher 2.01（可选）'
$ckLauncher.SetBounds(520, 20, 150, 22)
$grpC.Controls.Add($ckStart)
$grpC.Controls.Add($ckDgv)
$grpC.Controls.Add($ckLauncher)

$btnStatus = New-Object System.Windows.Forms.Button
$btnStatus.Text = '检查状态'
$btnStatus.SetBounds(10, 162, 130, 30)
$btnInstall = New-Object System.Windows.Forms.Button
$btnInstall.Text = '一键安装'
$btnInstall.SetBounds(150, 162, 170, 30)
$btnInstall.Font = New-Object System.Drawing.Font($btnInstall.Font, [System.Drawing.FontStyle]::Bold)
$btnUninstall = New-Object System.Windows.Forms.Button
$btnUninstall.Text = '卸载'
$btnUninstall.SetBounds(330, 162, 110, 30)

$btnTmOn = New-Object System.Windows.Forms.Button
$btnTmOn.Text = '进入测试模式'
$btnTmOn.SetBounds(10, 198, 150, 28)
$btnTmOff = New-Object System.Windows.Forms.Button
$btnTmOff.Text = '退出测试模式'
$btnTmOff.SetBounds(170, 198, 150, 28)
$lblTm = New-Object System.Windows.Forms.Label
$lblTm.Text = '（进/出都有 3 秒风险警告，重启生效）'
$lblTm.SetBounds(330, 203, 360, 22)

$log = New-Object System.Windows.Forms.TextBox
$log.Multiline = $true
$log.ReadOnly = $true
$log.ScrollBars = 'Vertical'
$log.Font = New-Object System.Drawing.Font('Consolas', 9)
$log.SetBounds(10, 236, 678, 330)
$log.Anchor = 'Left', 'Right', 'Top', 'Bottom'

$lblFree = New-Object System.Windows.Forms.Label
$lblFree.Text = '本程序开源、免费。如果您是付费得到这个程序的，请立即退款并举报卖家。'
$lblFree.ForeColor = [System.Drawing.Color]::DarkRed
$lblFree.SetBounds(10, 572, 678, 22)
$lblFree.Anchor = 'Left', 'Right', 'Bottom'

function Write-Log([string]$s) { $log.AppendText($s + "`r`n") }

function Get-GameDir {
    $g = $txtDir.Text.Trim().Trim('"')
    if (-not $g) { $g = 'D:\DMT3' }
    return $g
}

$btnStatus.add_Click({
    $log.Clear()
    Write-Log("== 状态检查 " + (Get-Date -Format 'HH:mm:ss') + " ==")
    try {
        Get-DdgStatus -GameDir (Get-GameDir) | ForEach-Object { Write-Log $_ }
    } catch { Write-Log("检查出错: $_") }
    Write-Log('—— 完 ——')
})

$btnInstall.add_Click({
    $g = Get-GameDir
    $fl = if ($rbTouch.Checked) { 'touch' } else { 'ir' }
    $wl = $ckLauncher.Checked
    $wd = $ckDgv.Checked
    if (-not (Test-Admin)) {
        Write-Log("请求 UAC 提权后在新窗口执行一键安装（$g, $fl, launcher=$wl, dgvoodoo=$wd）……")
        $ea = @('install', $g, $fl)
        if ($wl) { $ea += 'launcher' }
        if (-not $wd) { $ea += 'nodgv' }
        Invoke-Elevated -BatArgs $ea
        return
    }
    foreach ($b in @($btnInstall, $btnUninstall, $btnStatus)) { $b.Enabled = $false }
    Write-Log("== 一键安装 $g ($fl) ==")
    $form.Refresh()
    try {
        Invoke-FullInstall -GameDir $g -Flavor $fl -WithLauncher $wl -WithDgv $wd -Log { param($s) Write-Log $s }.GetNewClosure()
    } catch { Write-Log("安装出错: $_") }
    Write-Log('—— 安装结束 ——')
    foreach ($b in @($btnInstall, $btnUninstall, $btnStatus)) { $b.Enabled = $true }
})

$btnUninstall.add_Click({
    $g = Get-GameDir
    if (-not (Test-Admin)) {
        Write-Log("请求 UAC 提权后在新窗口执行卸载（$g）……")
        Invoke-Elevated -BatArgs @('uninstall', $g)
        return
    }
    foreach ($b in @($btnInstall, $btnUninstall, $btnStatus)) { $b.Enabled = $false }
    Write-Log("== 卸载 $g ==")
    $form.Refresh()
    try {
        Invoke-FullUninstall -GameDir $g -Log { param($s) Write-Log $s }.GetNewClosure()
    } catch { Write-Log("卸载出错: $_") }
    Write-Log('—— 卸载结束 ——')
    foreach ($b in @($btnInstall, $btnUninstall, $btnStatus)) { $b.Enabled = $true }
})

$btnTmOn.add_Click({
    Write-Log('== 进入测试模式 ==（弹出 3 秒警告）')
    if (Invoke-Testmode -On $true -SkipWarning $false) {
        Write-Log('完成。**重启电脑后生效。**')
    } else {
        Write-Log('已取消。')
    }
})

$btnTmOff.add_Click({
    Write-Log('== 退出测试模式 ==（弹出 3 秒警告）')
    if (Invoke-Testmode -On $false -SkipWarning $false) {
        Write-Log('完成。**重启电脑后生效。**')
    } else {
        Write-Log('已取消。')
    }
})

$form.Controls.Add($lbl)
$form.Controls.Add($txtDir)
$form.Controls.Add($btnBrowse)
$form.Controls.Add($grp)
$form.Controls.Add($grpC)
$form.Controls.Add($btnStatus)
$form.Controls.Add($btnInstall)
$form.Controls.Add($btnUninstall)
$form.Controls.Add($btnTmOn)
$form.Controls.Add($btnTmOff)
$form.Controls.Add($lblTm)
$form.Controls.Add($log)
$form.Controls.Add($lblFree)
Write-Log '一键安装会自动部署：StartKit（pakkey/读卡器模拟）+ RCGrandDogW32 stub + dgVoodoo2（可勾掉）+ 驱动/代理。'
Write-Log '建议先点「检查状态」。危险操作均有警告/UAC 提权。'
[void]$form.ShowDialog()
exit 0

# ---------------------------------------------------------------
# 本程序开源、免费。
# 如果您是付费得到这个程序的，请立即退款并举报卖家。
# ---------------------------------------------------------------
