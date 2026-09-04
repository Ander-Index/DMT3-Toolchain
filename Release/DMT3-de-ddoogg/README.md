# DMT3 免双狗发行套装（DMT3-de-ddoogg）

让 DJMAX TECHNIKA 3 在**不插两只实物加密狗**（SenseLock EL + Rockey6 SMART PLUS）
的情况下正常运行的完整发行包。三件套各管一层，按顺序部署即可。

> 适用场景：拿到一个全新的官方干净 DMT3 包，要让它免双狗正常运行。
> 本套装是 2026-09-01 实机复现验证过的完整流程。仅第 3 步（驱动）需要管理员权限。

```
DMT3-de-ddoogg\
├─ StartKit\      民间套件「MOD插件+虚拟读卡+启动加速」（wchdsk，2018）
├─ Launcher\      greg 自制「DJMAX Technika 3 Launcher 2.01」（2019-2020）
├─ De-DDOOGG\     本项目免狗包（2026）：虚拟狗驱动 + multiDLL 代理
├─ dgVoodoo2\     dgVoodoo2 图形转译层（Dege）——Windows 11 运行用
└─ 一键安装.bat    安装器（双击出图形界面 / 命令行
                  status|install|uninstall|testmode-on|testmode-off）
```

---

## 一、套装里分别是什么、从哪来

### 1. `StartKit\` —— 虚拟读卡 + MOD 插件（民间，2018）

官方游戏的 pak 解密密钥只存在于实物狗里（启动时从狗读取变换得出）。
这套件把这一层挪到了本地文件：

| 内容 | 作用 |
|---|---|
| `pakkey\`（61×128B） | 每个主 pak 的解密密钥库 |
| `CRT_R1.dll` | 「CardReader Emu for DMT series」——把密钥/读卡读取从狗重定向到 `pakkey\` 与本机 |
| `hid.dll` | 2018 原版（必须，Win11 新版 hid.dll 会破坏 65B 协议） |
| `CardNum.txt` | 模拟卡号（**可自行修改为自己的卡号**） |
| `Resource\config\`、`Resource\DiscInfo\` | MOD/启动加速的散文件覆盖层 |
| `用法.txt` | 原作者的使用说明 |

> 署名：Copyright (C) wchdsk 2018

### 2. `Launcher\` —— greg 自制启动器（2019-2020，可选）

> 非必需：不装这层也可以直接运行 Client.exe；需要启动器的更新/管理功能时再装。

| 内容 | 说明 |
|---|---|
| `launcher.exe` | 「DJMAX Technika 3 Launcher 2.01」，署名 greg；接管更新/启动流程 |
| `libver.dll` | 启动器配套库 |
| `LauncherSettings.ini` | 区域/下载设置（`region=China`） |
| `launcher.dat` | 启动器标记文件（如游戏目录已有可不覆盖） |

### 3. `De-DDOOGG\` —— 本项目免狗包（Kimi K3 & AnderX，2026）

狗①（SenseLock EL）运行时挑战应答 + 狗②（Rockey6）挑战应答的完整免狗层：

- `drivers\` itoken2（狗①枚举）+ vrockey6（狗② HID）虚拟驱动 + 签名证书
- `multiDLL\` 代理（`proxy_ir.dll` 红外版/**`proxy_touch.dll` 触控版** + 两个转发目标原件
  + `RCGrandDogW32_stub.dll` 狗② SDK stub）
  - 其中触控转发目标原件 `multiDLL_touch.dll` = wchdsk 的
    [WinTouch-to-Multi](https://github.com/wchdsk/WinTouch-to-Multi) V0.9（2018，红外屏信号→多点触控模拟器；
    启动时弹的 "Multi Emulator" 窗口就是它）
- `install.ps1` / `uninstall.ps1` 一键装/卸（管理员）
- `docs\实现原理.md` 技术细节、`source\` 完整源码与录制数据

详见 `De-DDOOGG\README.md`。

### 4. `dgVoodoo2\` —— Windows 11 运行用（Dege）

DMT3 的 `Client.exe` 是 2012 年 D3D9 独占全屏游戏，在 Win11 + 新显卡驱动下会初始化失败/白屏。
[dgVoodoo2](http://dege.freeweb.hu/)（Dege 的免费图形 API 转译层）把 D3D9 转译到 D3D11 解决此问题。
这里放的是**开箱即用的四件套 + 已调好的全屏配置**（dgVoodoo 2.87.3）：

- `D3D8.dll` / `D3D9.dll` / `D3DImm.dll` / `DDraw.dll` —— 复制到游戏目录即可
- `dgVoodoo.conf` —— 已按本项目实测可用的全屏配置调好，一并复制

---

## 二、部署步骤（全新干净官方包 → 免狗可玩）

> **版本红线**：本套装验证于 Client.exe（SHA256 前 16 位 `DFEECE61BF511BBF`）对应的
> 游戏版本。若你的干净包 Client.exe 不同版本，请勿照搬，先核对。

0. **备份**：把整个干净游戏目录复制一份留底。

1. **StartKit**：把 `StartKit\` 里的**所有内容**（pakkey\、CRT_R1.dll、hid.dll、
   CardNum.txt、Resource\）复制到游戏目录（覆盖同名文件；官方 CRT_R1.dll 可先改名备份）。
   需要改卡号就编辑 `CardNum.txt`。

2. **Launcher（可选）**：要民间启动器的更新/管理功能才把 `Launcher\` 里的文件复制到游戏目录
   （`launcher.exe` 覆盖官方启动器，官方的可先改名备份；`launcher.dat` 若已存在可跳过）。
   不需要就直接 `Client.exe` 启动。

3. **De-DDOOGG**：双击套装根目录的 **`一键安装.bat`** → 选游戏目录和代理版本 →
   点「一键安装」（非管理员会自动弹 UAC 提权）。若测试模式是本次才开启的，
   驱动要重启后才能装——安装器会自动挂一个一次性开机任务，**重启登录后自动续装**，
   无需手动重跑（也可重启后手动再点一次「一键安装」，效果相同）。
   命令行也可以：`一键安装.bat status|install|uninstall|testmode-on|testmode-off [游戏目录] [ir|touch]`。
   也可以手动跑 `De-DDOOGG\install.ps1`（等效，见该包 README；手动跑时若提示重启，重启后需自己再跑一次）。

   安装器/脚本会依次做（中途如提示重启，重启后再跑一次）：
   1. 导入测试证书（`drivers\*.cer`，Root + TrustedPublisher）
   2. 开启 testsigning（`bcdedit /set testsigning on`，**需重启一次**）
   3. `pnputil` 安装 itoken2 / vrockey6 驱动包
   4. `devcon` 创建两个虚拟设备节点（狗① `root\vid_0471&pid_485d`、狗② `root\vrockey6`）
   5. 部署 multiDLL 代理到游戏目录

   代理 flavor：
   - `-Flavor ir`：红外版代理，启动无弹窗（**推荐**）
   - `-Flavor touch`：触控版代理，启动弹 "Multi Emulator" 窗口，**需手动点掉**

   手动核对（脚本不覆盖的两件）：
   - `hid.dll` 已在（StartKit 已带）
   - `RCGrandDogW32.dll` 换成 `De-DDOOGG\multiDLL\RCGrandDogW32_stub.dll`
     （原版改名 `RCGrandDogW32_orig.dll` 备份）

   **系统层验证**（普通 PowerShell）：
   ```
   sc query itoken2v2      → RUNNING
   sc query vrockey6       → RUNNING
   pnputil /enum-devices   → 能看到 "Virtual Senselock EL Dongle" 和 "Virtual Rockey6 SMART PLUS Dongle"
   ```

   注意：
   - 测试证书为 `DMT3 De-DDOOGG`（O=Kimi K3 and AnderX），有效期至 **2099-12-31**，
     实际不会过期；驱动签名未带时间戳（已装好的机器重装/换机才需要导入证书）
   - 需关闭安全启动（Secure Boot）和内存完整性（HVCI），否则测试签名驱动不加载

   #### 为什么必须开"测试模式"？（以及有没有别的办法）

   **这不是 Windows 11 的新规矩**——64 位 Windows 从 2007 年的 Vista x64 起，
   就强制所有内核驱动必须带有效签名。Windows 只允许两类驱动加载：

   1. **微软签名**（WHQL 或 Attestation，需购买 EV 代码签名证书 + 企业资质）
   2. **测试签名**（自签证书）+ 系统处于测试模式（testsigning on）

   本套装的两个虚拟狗驱动是我们自己编写的内核驱动——游戏枚举加密狗依赖内核设备栈
   （cfgmgr32/HID），必须在系统里真实"存在"两只 USB 狗，这一步用户态程序做不到，
   所以绕不开内核驱动，也就绕不开测试模式（第 2 条免费路线）。

   其他常见"绕过"为什么不行：
   - 开机时"禁用驱动程序强制签名"：只对当次启动有效，重启即失效，没有实用性
   - 让用户各自自签：自签同样需要测试模式，反而多步骤（想自己签也完全可以，
     源码和构建脚本都在 `De-DDOOGG\source\drivers\`）
   - 纯用户态免驱动：没有内核驱动就没有可供枚举的"狗"，代理拦不到枚举阶段
   - 借用带漏洞的第三方已签名驱动（BYOVD）：那是恶意软件的做法，不做

   如果有条件购买 EV 证书并做微软 Attestation 签名，就可以摘掉测试模式要求
   （驱动源码不变，重签即可）。

   **如何进入 / 退出测试模式**

   - 用安装器：双击 `一键安装.bat` → 「进入测试模式」/「退出测试模式」按钮
     （都会先弹 **3 秒风险警告**；非管理员自动 UAC 提权）
   - 或命令行：`一键安装.bat testmode-on` / `testmode-off`
   - 或手动（管理员 cmd）：`bcdedit /set testsigning on`（进）/ `bcdedit /set testsigning off`（出）
   - **两者都要重启电脑才生效**；进入前还需先关 Secure Boot 和内存完整性（HVCI）

   **进入测试模式带来的影响**

   - 桌面右下角常驻「测试模式 Windows …」水印（无害，只是提醒）
   - 系统驱动加载门槛降低：任何测试签名的驱动都能加载——这是固有安全权衡，
     不玩的时候可以「退出测试模式」关回去（退出后虚拟狗不加载，游戏需插回实物狗）
   - 个别带反作弊的游戏/软件会拒绝在测试模式下运行（与本游戏无关）

4. **Win11 显示修复**：把 `dgVoodoo2\` 里的 4 个 dll + `dgVoodoo.conf` 复制到游戏目录。

5. **诊断日志目录**（可选但建议）：
   ```powershell
   New-Item -ItemType Directory -Force D:\DMT3
   ```
   代理会把诊断日志写到这里（`ioctl.log` / `rw.log` 等）。缺此目录不影响运行，只是没日志。
   （`rw.log` 会预分配涨到 ~290MB，属正常现象。）

6. **拔掉两只实物狗**（狗① SenseLock EL / 狗② Rockey6，VID 0471 / 096E），双击 `Client.exe`。
   正常的话：Logo → 标题 → 选歌 → 能打歌即全通。
   想看免狗日志特征：`D:\DMT3\ioctl.log` 应为 0x47 大量透传 + 0x22 罐头 + 0x39×1，
   且无 0xDEAD miss（日志为二进制：9 字节 `IOCTLOG1\n` 头 + 8224B 定长记录）。

---

## 三、关于"内容更新包"（不包含在本套装内）

本项目历史上存在过一次内容更新（新增 pattern04、movie2001 等 10 个 pak 及配套数据），
出自当时的**私服**。NEOWIZ 发出警告后：私服 MAX SHOP 停运，更新内容已全部撤下。
因此本套装**不包含也不提供**任何私服更新内容——上述部署流程只依赖官方干净包 + 三件套，即可完整游玩。

> 补充说明：`file\`（每首歌的解锁/存档数据）与 `client.dat`（4 字节内容版本标记）
> 属内容版本绑定文件——若你的游戏目录与验证版同版本，可从任何已跑通的目录拷贝；
> 没有也没关系（游戏会重建/回退默认）。

---

## 四、故障速查

| 症状 | 原因 | 处置 |
|---|---|---|
| 启动后几秒~几分钟崩，WER 报 `0xc0000409 @ Client.exe+0x15f9d3` | **内容层不齐** | 逐项核对部署步骤 1-2，优先查 `pakkey\` 是否在、`Resource\` 是否完整 |
| 弹 "Usb Lock Error." | 虚拟狗①没起来 | `sc query itoken2v2`；没装回步骤 3 |
| 游戏枚举不到狗② | vrockey6 没起来 | `sc query vrockey6`；检查 `pnputil /enum-devices /class HIDCLASS` |
| 白屏/初始化失败（Win11） | D3D9 兼容问题 | 部署 dgVoodoo2（步骤 4） |
| 触控版启动卡住不动 | Multi Emulator 弹窗没人点 | 点掉它，或换红外版代理 |
| 驱动装不上/服务起不来 | 安全启动/HVCI 没关 | 关 Secure Boot + 内存完整性 |
| 装完提示"有设备未就绪"/devcon failed（Win10） | 旧版驱动包 INF 与 Win10 不兼容（OS 限定 22000+ / MsHidKmdf 引用结构差异，报 0xe0000219） | 换新套装重跑安装即可：会自动清掉旧驱动包和半残设备节点再重装 |

---

## 五、回滚

- 用干净备份整目录覆盖回去即可（部署前的备份在此派用场）。
- 系统层卸载：管理员跑 `De-DDOOGG\uninstall.ps1`。

---

## 六、许可与致谢

| 组件 | 作者 | 许可/说明 |
|---|---|---|
| `StartKit\` | **wchdsk**（2018；`CRT_R1.dll` 版权信息署名 "Copyright (C) wchdsk 2018"） | 版权归原作者所有；仅作存档/研究用途分发 |
| `Launcher\` | **greg**（DJMAX Technika 3 Launcher 2.01） | 版权归原作者所有 |
| `De-DDOOGG\` | **Kimi K3 & AnderX** | 代码 CC BY-NC-SA 4.0（禁止商用/保留署名/改后开源） |
| `De-DDOOGG\multiDLL\multiDLL_touch.dll` | **wchdsk**（[WinTouch-to-Multi](https://github.com/wchdsk/WinTouch-to-Multi) V0.9，2018） | 版权归原作者所有；仅作程序转发目标 |
| `dgVoodoo2\` | **Dege**（dgVoodoo 2.87.3，©2013-2026，免费软件） | 作者允许自由分发；[官网](http://dege.freeweb.hu/) |

- 游戏本体及全部资源版权归 **Pentavision / NEOWIZ** 所有。本套装不含任何游戏资源文件，
  仅面向已合法拥有游戏的用户做兼容性与存档研究。