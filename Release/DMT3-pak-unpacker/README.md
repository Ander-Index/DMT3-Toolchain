# DMT3 .pak 解包器

> **Kimi K3 & AnderX**

DJMAX TECHNIKA 3 资源包（`pack\*.pak`）解包工具。
单文件、全明文脚本，Windows 10/11 自带环境直接运行，**无需安装** Python / .NET / 任何东西。

## 用法

### 双击运行（图形界面）

双击 `DMT3解包器.bat` → 把 pak 文件或装着 pak 的文件夹**拖进列表** → 选好输出目录 → 点「开始解包」。

输出结构：`<输出目录>\<pak名>\Resource\...`（与游戏内资源路径一致）

### 命令行

```
DMT3解包器.bat <pak文件或文件夹...> [-o 输出目录]
```

例：

```
DMT3解包器.bat "D:\game\pack\Sound.pak" "D:\game\pack" -o "D:\out"
```

终端里直接把文件/文件夹拖进窗口即可自动填路径。
不带 `-o` 时输出到当前目录下的 `DMT3_Unpack\`。
可选：`--pakkey-dir <目录>` 指定外部密钥目录（一般不需要，见下）。

## 特性

- 内嵌全部 61 个主 pak 的密钥（pakkey），拷走 bat 单文件即可解官方全部 98 个 pak
- 遇到没见过的 pak（例如更新版新增包）会**自动破解**描述符密钥
  （已知明文攻击，每个描述符最多试 256 个密钥字节），日志里标 `[自动破解]`
- 支持 >2GB 的超大 pak（movie11.pak 2.27GB 等，内存映射读取）
- 启动自检：密钥流（sin/cos 精度路径）和 LZ 解压结果与游戏本体逐位比对，
  不一致会直接报错而不是解出垃圾

## 注意事项

- 首次双击可能弹 SmartScreen「未知发布者」提示，选「仍要运行」即可
  （纯文本脚本，可自行审查全部内容）
- 不要把 bat 放在路径含单引号（`'`）的目录里
- pak 里的 `.pt` 谱面文件解出后是原始密文（PTFF 容器层已解），
  谱面二次解密请用配套的 **DMT3-pt-converter**（同为单文件 bat，用法一致），本工具不做

## 技术

批处理引导 + PowerShell 现场编译内嵌 C#（.NET Framework 系统自带）。
解包算法完全逆向自 Client.exe：头部 sin/cos 密钥流 + XOR 链、
描述符双层 XOR、数据区 LZO1X（游戏 `0x709EF0`）、按种子掩码前 1MB。
已与参考输出全量逐字节回归验证（98 个 pak、7 万+ 文件）。

## 许可证

本工具代码以 **CC BY-NC-SA 4.0** 发布：随意使用但禁止商用、原样分发须保留署名、
修改后须以相同条款开源。详见 [LICENSE.txt](LICENSE.txt)。

## 致谢

- [samnyan/DMTQ-Tools](https://github.com/samnyan/DMTQ-Tools)（DJMAX Technika Q 工具集）——
  配套 `.pt` 谱面解密工具（`scripts\pt_cipher.py`）的算法曾与其 `PtCipher.cs` 交叉验证。
  本解包器（pak 容器层）为独立逆向，不含该库代码。
  注：该仓库自身代码未声明许可证；其 `LICENSE.txt` 仅覆盖捆绑依赖
  （UnpackMe.SDK.Standard：MIT © HSReina；lz4net：BSD © Milosz Krajewski）。

---

*Kimi K3 & AnderX, 2026-08-31*
