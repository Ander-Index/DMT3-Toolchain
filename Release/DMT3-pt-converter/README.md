# DMT3 .pt 谱面转换器

> **Kimi K3 & AnderX**

DJMAX TECHNIKA 3 谱面文件（`.pt`，PTFF 格式）解密工具。
单文件、全明文脚本，Windows 10/11 自带环境直接运行，**无需安装** Python / .NET / 任何东西。

配合 pak 解包器使用：先用 `DMT3-pak-unpacker` 解出 pak，再用本工具解密散落在
各目录里的 `.pt`（解包器输出中的 pt 是容器层明文、谱面层密文）。

## 用法

### 双击运行（图形界面）

双击 `DMT3谱面转换器.bat` → 把 pt 文件或文件夹**拖进列表** → 选好输出目录 →
点「开始转换」。文件夹会递归扫描其中所有 `.pt`，输出保持相对目录结构。

**覆盖模式**：勾选「覆盖解密前的 pt（不可逆）」后，输出目录会置灰，
转换结果直接写回原文件。**该加密不可逆，覆盖后无法恢复密文，请确认已备份。**

### 命令行

```
DMT3谱面转换器.bat <pt文件或文件夹...> [-o 输出目录] [-i]
```

- `-i, --in-place`：覆盖模式（原地改写，不可逆）
- 不带 `-o` 时输出到当前目录下的 `DMT3_pt_decrypted\`
- 终端里直接把文件/文件夹拖进窗口即可自动填路径

## 特性

- **自动识别**：DMT3 的 pak 里混有极少数本就未加密的 pt（tutorial/demo 共 4 个），
  工具会自动识别——密文正常解密，明文原样复制（输出目录模式）或跳过（覆盖模式），
  不会把明文再"解密"成乱码
- 启动自检：内嵌真实密文样本 + 已知答案 SHA-256，算法移植出错会直接报错
- 已全量回归验证：735 个 pt 与参考解密结果**逐字节一致**

## 注意事项

- 首次双击可能弹 SmartScreen「未知发布者」提示，选「仍要运行」即可
  （纯文本脚本，可自行审查全部内容）
- 不要把 bat 放在路径含单引号（`'`）的目录里
- 覆盖模式不可逆，建议先用输出目录模式验证效果

## 许可证

本工具代码以 **CC BY-NC-SA 4.0** 发布：随意使用但禁止商用、原样分发须保留署名、
修改后须以相同条款开源。详见 [LICENSE.txt](LICENSE.txt)。

## 致谢

- [samnyan/DMTQ-Tools](https://github.com/samnyan/DMTQ-Tools)（DJMAX Technika Q 工具集）——
  本工具的 PT 解密算法（MT19937 密钥流 + 反馈 TEA）曾与其
  `DMTQ.Tools.Core/Services/Pattern/PtCipher.cs` **交叉验证**（未复制代码）。
  注：该仓库自身代码未声明许可证；其 `LICENSE.txt` 仅覆盖捆绑依赖
  （UnpackMe.SDK.Standard：MIT © HSReina；lz4net：BSD © Milosz Krajewski）。

---

*Kimi K3 & AnderX, 2026-08-31*
