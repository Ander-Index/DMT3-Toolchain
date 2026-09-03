# De-DDOOGG — DMT3 双狗免狗分发包

**作者：Kimi K3 & AnderX**（代码许可：CC BY-NC-SA 4.0）

拔掉两只实物加密狗（狗① Senselock EL / 狗② Rockey6 SMART PLUS）后，游戏照常运行。
2026-08-28 实机验证通过（双狗全拔，红外屏版 / 触控屏版均正常游玩）。

> 本包仅供个人学习与自有设备研究使用。内含该游戏加密狗的录制应答数据与游戏原版 DLL
> 备份，再分发请注意游戏厂商与加密狗厂商的相关条款。

---

## 1. 内容物

```
De-DDOOGG\
├── install.ps1 / uninstall.ps1   一键安装/卸载（管理员）
├── README.md                     本文件
├── docs\
│   └── 实现原理.md                技术实现文档（原理、数据流、已知边界）
├── multiDLL\
│   ├── proxy_ir.dll              免狗代理·红外屏版（转发到 multiDLL_orig.dll）
│   ├── proxy_touch.dll           免狗代理·触控屏版（转发到 multiDLL_touch.dll）
│   ├── multiDLL_orig.dll         红外屏原版 multiDLL 原件（24KB）
│   └── multiDLL_touch.dll        触控屏适配版 multiDLL 原件（214KB，wchdsk 的 WinTouch-to-Multi V0.9）
├── drivers\
│   ├── DMT3-De-DDOOGG.cer        测试签名证书（公钥，安装时导入；有效期至 2099-12-31）
│   └── DMT3-De-DDOOGG.pfx        证书私钥（仅重新签名驱动时需要，密码 ddoogg；见 §6 隐私与安全）
│   ├── itoken2\  (inf/sys/cat)   虚拟狗①枚举驱动（已签名）
│   └── vrockey6\ (inf/sys/cat)   虚拟狗② HID 驱动（已签名）
├── tools\
│   └── devcon.exe                微软 WDK 设备控制台（创建 root 设备节点用）
├── extra\
│   └── dgVoodoo.conf.fullscreen  dgVoodoo2 全屏配置（可选，Win11 显示修复）
└── source\                       全部源代码（见 §7 自行编译）
    ├── drivers\                  两个内核驱动的 C 源码 + inf + cdf + make_drivers.bat
    └── proxy\                    代理 DLL 构建器（Python）+ 录制的狗应答数据（gzip）
```

## 2. 系统要求与兼容性

| 项 | 要求 |
|---|---|
| 操作系统 | Windows 10 / 11 **64 位**（驱动为 x64；游戏本体 32 位不受影响） |
| 权限 | 安装/卸载需管理员 |
| **安全启动（Secure Boot）** | **必须关闭**（开启测试签名模式的前提） |
| **内存隔离（HVCI）** | **必须关闭**：设置 → 隐私和安全性 → Windows 安全中心 → 设备安全性 → 内核隔离 → 内存完整性 = 关。HVCI 开启时测试签名驱动无法加载 |
| 测试签名模式 | 必须开启（`bcdedit /set testsigning on`，install.ps1 自动处理，需重启一次） |
| 证书有效期 | 测试证书 `DMT3 De-DDOOGG`（O=Kimi K3 and AnderX），有效期至 **2099-12-31**（signtool 实测可用的最远日期），实际不会过期。驱动签名未带时间戳。重新签名：`drivers\DMT3-De-DDOOGG.pfx`（密码 `ddoogg`） + signtool，见 §7 |

> **为什么必须开测试模式？** 这不是 Windows 11 的新规矩：64 位 Windows 自 2007 年
> Vista x64 起强制所有内核驱动必须有有效签名。Windows 只加载两类驱动——微软签名
> （WHQL/Attestation，需付费 EV 证书+企业资质）或 测试签名（自签证书）+测试模式。
> 虚拟狗驱动必须在系统里真实"存在"两只 USB 狗供游戏枚举（内核设备栈，用户态做不到），
> 所以走免费的测试签名路线，测试模式不可免。临时启动菜单里的"禁用驱动强制签名"仅
> 当次有效，不具备实用性。若有条件做 EV+Attestation 签名，用 source\ 重签即可摘掉测试模式。

VBS/凭据保护等其他虚拟化安全特性未做逐一验证；如安装后驱动无法加载，优先检查上面三项。

## 3. 安装

```powershell
# 右键 PowerShell → 以管理员身份运行：
# 红外屏：
powershell -ExecutionPolicy Bypass -File D:\De-DDOOGG\install.ps1 -GameDir "游戏目录" -Flavor ir
# 触控屏：
powershell -ExecutionPolicy Bypass -File D:\De-DDOOGG\install.ps1 -GameDir "游戏目录" -Flavor touch
```

- `-GameDir` 默认 `D:\DMT3`（Client.exe 所在目录）；`-Flavor` 默认 `ir`
- 若提示已开启 testsigning 并要求重启 → **重启后再跑一遍同一命令**
- 完成后拔掉两只实物狗，直接启动游戏（触控版启动会先弹 "Multi Emulator" 窗口，属该版本的正常现象）

## 4. 切换红外/触控版本

```powershell
install.ps1 -GameDir "游戏目录" -Flavor touch   # 切到触控版
install.ps1 -GameDir "游戏目录" -Flavor ir      # 切回红外版
```

或手动：把 `proxy_ir.dll` / `proxy_touch.dll` 复制为游戏目录下的 `multiDLL.dll`
（两个转发目标 `multiDLL_orig.dll` / `multiDLL_touch.dll` 已常驻游戏目录，无需动）。

## 5. 验证

- 设备管理器：`Virtual Senselock EL Dongle`（系统设备）+ `Virtual Rockey6 SMART PLUS Dongle`（HID 类）
- 游戏运行后游戏目录出现 `ioctl.log` 且约两千条记录（诊断用；无此文件不影响运行）
- 正常进菜单、可游玩 = 成功

## 6. 本软件会对计算机做出的更改（完整清单）

**安装（install.ps1）所做的全部更改：**

| 类别 | 更改 | 位置/方式 |
|---|---|---|
| 启动配置 | 开启测试签名模式 | `bcdedit /set testsigning on`（需重启生效） |
| 证书 | 导入测试证书公钥 | 本地计算机 → 受信任的根证书颁发机构 + 受信任的发布者（`DMT3 De-DDOOGG`） |
| 驱动包 | 两个驱动包进入系统驱动存储区 | `pnputil /add-driver`（生成 oemXX.inf，文件复制到 `C:\Windows\System32\DriverStore`） |
| 设备 | 创建两个 root 虚拟设备 | `ROOT\SYSTEM\000x`（itoken2v2）和 `ROOT\HIDCLASS\000x`（vrockey6） |
| 服务 | 注册两个内核服务（手动启动，仅设备存在时运行） | `itoken2v2`、`vrockey6` |
| 游戏目录 | 替换 `multiDLL.dll`（原文件改名备份为 `multiDLL_orig.dll`）；新增 `multiDLL_touch.dll` | 游戏目录内 |

**运行时的行为：**

- 代理 DLL 会尝试在 `D:\DMT3\` 下写诊断日志（`ioctl.log`/`rw.log` 等）；目录不存在则静默不写，**不影响免狗功能**
- 无网络通信、无后台驻留进程、无计划任务、无开机启动项
- 两个驱动只在系统中存在对应虚拟设备时运行，不钩子任何系统调用、不拦截其他程序

**卸载（uninstall.ps1）**：移除两个虚拟设备 → 删除两个驱动包 → 游戏 DLL 还原为红外屏原版
并删除 `multiDLL_touch.dll`。测试签名模式与导入的证书**保留**（如需还原：
`bcdedit /set testsigning off` 重启；证书在证书管理器中删除 `DMT3 De-DDOOGG`）。

## 7. 隐私与安全审计声明（2026-08-28 全量代码审计）

已审计本包全部源代码与二进制（`source\` 下全部、`multiDLL\`、两个驱动、脚本）：

- **无个人隐私内容**：不含任何用户名、机器名、机器 GUID、IP、账号、浏览器/文件记录；
  二进制内无任何指向特定电脑的路径（唯一硬编码路径为通用目录 `D:\DMT3\*.log`）
- **无网络行为**：全部代码均不发起任何网络通信
- **狗应答数据**：代理 DLL 与 vrockey6 驱动内嵌两只**加密狗**的录制应答数据
  （属硬件狗的数据，非个人隐私；这也是本方案的核心）
- **DMT3-De-DDOOGG.pfx** 是测试签名**私钥**（密码 `ddoogg`）：持有者可签发在本机被信任的驱动。
  仅供重新签名本包驱动使用；请勿用它签名无关软件，分发本包给不信任的人时可删掉它
  （安装只需 .cer 公钥）
- 测试签名驱动本身会降低系统的驱动加载门槛（这是 testsigning 的固有性质）；
  如不再需要，建议按 §6 末尾还原

## 8. 从源代码编译

### 8.1 两个内核驱动（source\drivers\）

环境：Visual Studio BuildTools（MSVC x64）+ Windows SDK/WDK 10（开发时用的 10.0.28000.0）。

```bat
rem 按需修改 make_drivers.bat 顶部的 WDK/VS 路径，然后：
cd source\drivers
make_drivers.bat
rem 得到 itoken2.sys / vrockey6.sys；随后用你自己的测试证书签名：
makecat itoken2.cdf
makecat vrockey6.cdf
signtool sign /fd sha256 /s My /n "你的测试证书名" itoken2.sys itoken2.cat vrockey6.sys vrockey6.cat
```

### 8.2 免狗代理 multiDLL（source\proxy\）

环境：Python 3（32/64 位均可）+ `pip install keystone-engine`。

```bat
cd source\proxy
rem 选择转发目标：编辑 build_rw_replay.py 顶部  BACKING = 'orig'（红外）或 'touch'（触控）
python build_rw_replay.py
rem 产物：multiDLL_rwreplay.dll（BACKING=orig）或 multiDLL_rwreplay_touch.dll（BACKING=touch）
rem 即分发包里的 proxy_ir.dll / proxy_touch.dll
```

- 代理是**自研 PE/汇编构建器**（`pebuild.py` + keystone 汇编）生成的纯汇编 DLL，
  不需要 C 编译器
- `data\*.gz` 是构建必需的狗应答录制（gzip 压缩，构建脚本自动解压读取）
- 已验证：本源码包独立构建的产物与包内预置 DLL **逐字节一致**

## 9. 用到的开源 / 第三方组件

| 组件 | 用途 | 许可/来源 |
|---|---|---|
| **keystone-engine** | 代理 DLL 构建时的 x86 汇编器 | GPLv2，https://www.keystone-engine.org （`pip install keystone-engine`） |
| **Python 3** | 代理 DLL 构建脚本运行时 | PSF License，https://www.python.org |
| **devcon.exe** | 安装时创建 root 设备节点 | 微软专有工具（随 Windows SDK/WDK 提供，tools\ 内为原样拷贝） |
| **Windows SDK / WDK** | 驱动编译工具链与头文件 | 微软专有，需自行安装 |
| **dgVoodoo2** | （可选）Win11 显示修复，仅附带配置文件 | dege 的免费软件（非开源），https://dege.freeweb.hu |
| multiDLL 原件 ×2 | 游戏自带的两个 DLL 变体（红外官方版 / 民间触控适配版 = wchdsk 的 [WinTouch-to-Multi](https://github.com/wchdsk/WinTouch-to-Multi) V0.9） | 各自权利人所有，仅作备份与转发目标 |

其余（pebuild.py、build_rw_replay.py、itoken2.c、vrockey6.c、install/uninstall 脚本）均为本项目自研代码。

## 10. 常见问题

- **杀毒软件**可能拦截驱动安装或代理 DLL，请加白名单。
- 游戏更新替换 multiDLL.dll 后，重跑 install.ps1 即可。
- 只免这两只狗；真狗官方驱动（slusb/slvbus/slvrd）与本包互不影响，可共存。
- `extra\dgVoodoo.conf.fullscreen`：覆盖游戏目录的 `dgVoodoo.conf` 即全屏，与免狗无关。

---

*De-DDOOGG by **Kimi K3 & AnderX** — 本程序开源、免费；如果您是付费得到这个程序的，请立即退款并举报卖家。*
