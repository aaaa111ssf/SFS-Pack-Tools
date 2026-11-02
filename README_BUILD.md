# SFS Pack Tool v2.3.6-PyQt — Windows 打包 + 签名套件

本目录就是完整的构建材料，放在 Windows 上即可一键生成"内置 AssetRipper 1.1.4、已用你的证书签名"的单文件 EXE。

## 需要什么

- Windows 10/11 x64
- 已安装 Python 3.10（`python --version` 能打印版本即可）
- 依赖见 `requirements.txt`（`python -m pip install -r requirements.txt`）：**PyQt5 5.15.11**、
  numpy、Pillow、python-dateutil、pyperclip、UnityPy、PyInstaller
- **PyQt-SiliconUI 不需要装**：`siui/` 已经内置在本目录（它没发布到 PyPI）
- 注意：PyInstaller 的 `excludes` 里**不能排除 PIL**，UnityPy 一 import 就要它
- 签名需要 `signtool.exe`（安装 Windows SDK 后自带，脚本会自动定位）

## 一、一键操作（最省事）

双击 `build_and_sign.bat`，它会依次完成：解压内置 AssetRipper → 准备许可证 → 装依赖 → 打包 → 签名 → 验证。

完成后 EXE 在：

```
dist\SFS_Pack_Tool_v2.3.6-PyQt_Embedded_GPL.exe
```

## 二、分步操作

| 文件 | 作用 |
| --- | --- |
| `build.bat` | 只打包，不签名 |
| `sign.bat` | 只对 `dist\*.exe` 签名（用 `certs\codesign.pfx`，密码已内置） |

## 目录结构

| 文件/目录 | 说明 |
| --- | --- |
| `sfs_pack_tool_gui.py` | 界面层（PyQt5 + SiliconUI，含"标准区 + __CANDIDATES__ 人工确认区"） |
| `sfs_pack_tool_logic.py` | 业务层：导出 / 并入 / 剥离 / 提取 / 回滚 / 预览，不含 GUI 依赖 |
| `siui/` | PyQt-SiliconUI（GPL-3.0）内置副本，界面用的圆角卡片/按钮/开关/进度条 |
| `legacy/` | 旧 Tkinter 界面留档，不参与打包 |
| `sfs_project_exporter.py` | 导出模块（已修复空类语法） |
| `SFS_Pack_Tool.spec` | PyInstaller 打包配置 |
| `AssetRipper_win_x64-1.1.4.zip` | 内置 AssetRipper 官方运行包 |
| `SFS_Pack_Tool_v22.ico` | 程序图标 |
| `LICENSE-GPL-3.0.txt`、`GPL_COMPLIANCE.md` | GPL 合规材料，打包进 `licenses/` |
| `certs/codesign.pfx` | 你的代码签名证书（密码：20100622xu） |
| `certs/codesign.cer / .spc / .pvk` | 同一证书的其他格式备份/公钥材料 |

## 签名说明

- 证书主体 `CN=AFuturestar`，SHA-256 Authenticode 签名，并加可信时间戳（DigiCert）。
- 该证书不是 Windows 预置信任根，因此首次运行可能仍会提示"发布者未知/SmartScreen"。可自行在时间戳后追加信任，或按你的分发策略处理。

## 脚本里可改的地方

- 证书/密码：改 `sign.bat` 顶部的 `PFX` 与 `PWD` 两行。
- 时间戳服务器：改 `sign.bat` 中 `-t` 参数的 URL。

> 密码 20100622xu 以明文写在 `sign.bat` 里，仅用于本地自动签名。请勿把 `certs\` 与 `sign.bat` 一起泄露给他人。

---

## 打安装包（NSIS）

1. 先出目录版（onedir）：`python -m PyInstaller SFS_Pack_Tool_onedir.spec --noconfirm`
   → `dist/SFS_Pack_Tool_v2.3.6-PyQt_portable/`
2. 编译安装包：`third_party/nsis-3.10/makensis.exe -V2 SFS_Pack_Tool_Setup.nsi`
   → `dist/SFS_Pack_Tool_v2.3.6-PyQt_Setup.exe`（LZMA solid，约 78 MB，3~7 分钟）
3. 静默验证：`Setup.exe /S /D=D:\SFS_Test`；卸载 `D:\SFS_Test\卸载.exe /S`

三个坑（都踩过）：

- `SFS_Pack_Tool_Setup.nsi` 必须存成 **UTF-8 with BOM**，否则 makensis 直接报 `Bad text encoding`。
- Git Bash 里传 `/V2` 会被当成路径转换，用 `-V2` 或先 `MSYS2_ARG_CONV_EXCL="*"`。
- NSIS 用的是免安装 zip（`third_party/nsis-3.10/`），不往系统里装东西。
