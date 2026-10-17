# SFS Pack Tool — User Guide / 工具介绍

V2.3.4 · Author / 作者: A Future star · QQ Group / QQ 群: 923038827

Language / 语言: [🇬🇧 English](#English) ｜ [🇨🇳 中文](#中文)

---

# English

## 1. What this tool solves

An SFS mod pack (`.pack`) contains Unity asset bundles (prefabs, textures, materials, audio) plus an optional custom-script DLL. To edit it, use it, or rebuild it into your own parts, you first need a real Unity project — and a project produced by the official AssetRipper has almost everything broken:

- Script references can't resolve → a wall of `Script is missing`
- Texture / material references are dangling → hundreds of Odin `reference has gone missing` errors
- Parts render as a solid black board (with no error at all)
- `RenderSortingModule.SetDepth` throws `NullReferenceException`

This tool fills all those potholes at once: unpack, align, repair, merge, install.

**In one line:** make mod parts load in the Toolkit with nothing missing.

## 2. Feature overview

| Feature | Description |
| --- | --- |
| Localization | Extract translatable text → translate the JSON → write it back into a localized pack |
| Pack info | See which platforms the pack has, how many parts, whether custom scripts are bundled |
| Strip | Keep only the target platform — the `.pack` shrinks a lot |
| One-click export | Turn the `.pack` into a Unity project you can just open (fully automated) |
| Script alignment | Rewrites prefab script references to the Toolkit's real scripts |
| Black-board fix | Parts rendering as a solid black board? Swaps the placeholder shader back for the real one |
| Dangling-reference repair | Missing texture / material / audio references are re-linked or copied back by name |
| Asset grouping | Mod-owned assets are filed under `Assets/<mod name>/` by type |
| Merge package | Builds a clean merge package containing only what your Toolkit lacks |
| Install into Toolkit | Installs straight into your project — with a backup first, and your healthy files left alone |

The UI has a **中文 / English** switch at the top; the interface and logs are bilingual.

## 3. Usage

### 3.1 Localization

1. Click **Select source mod.pack**.
2. Click **Extract text** → produces `texts_to_translate.json` (output path configurable; defaults next to the source pack).
3. Translate the JSON. Format: `{ "original": "translation" }` — only include entries you actually changed.
4. Click **Select translation JSON**, then **Write localization & build pack** → outputs `mod_CN.pack`.
5. The **Translator tag** field is appended to the asset's `Author` field (default: `〈A Future star汉化〉`).

Built-in filtering avoids changing internal identifiers: a 38-word blacklist (`Toggle`, `Metal`, `mass`, …) plus a 16-field whitelist (`DisplayName`, `Description`, …), so only genuinely user-facing text is touched.

### 3.2 Pack info / Strip

- **Pack info:** reports whether each platform (Windows / Android / Mac / iOS) is present, how many parts there are, and whether a `CodeAssembly` (custom scripts) is bundled. The part count is derived from prefab root objects, so it isn't inflated.
- **Strip:** pick a target platform → produces a `.pack` containing only that platform, much smaller. It refuses to continue if the target platform isn't in the pack or if the output path equals the source file, protecting the original pack from being overwritten.

### 3.3 One-click export into the Toolkit (main feature)

1. Click **Select project dirs**. This button asks for two directories:
   - First, the Modding Toolkit root (containing `Assets/Scripts`).
   - Then, the original mod project directory (optional, but strongly recommended because it enables automatic dangling-reference repair).
2. Tick **Install into Toolkit after export**. Leave it unchecked to only build a merge package without touching your project.
3. Click **One-click export** and wait for the process to finish.

The tool automatically runs the following steps:

```text
Scan pack information
  → AssetRipper export
  → Script alignment
  → Placeholder-shader repair
  → Mod asset grouping
  → Build merge package
  → Install into Toolkit (optional)
  → Post-export self-check
```

Output is saved to `%TEMP%\SFS_Pack_Stage\<pack name>_export\`. This is a temporary directory and can be deleted when no longer needed.

### 3.4 Repair the Toolkit

The **Repair Toolkit (stub shaders · dangling references)** button cleans up a project that has already been damaged:

- Removes AssetRipper placeholder shaders that may have been imported (the cause of the black-board rendering issue).
- Scans the project for references to non-existent GUIDs and re-links or restores assets by name.
- Lists items with no recoverable source in `_PackToolBackup\<timestamp>_dangling\dangling_manifest.txt` for manual review.

> For automatic repair, you must provide the original mod project directory. Without it, the tool only scans and will not modify your files.

## 4. Safety mechanisms

| Mechanism | Description |
| --- | --- |
| Merge gate | If any script reference cannot be resolved, merging is blocked. A dialog lists the class names and `UNRESOLVED_SCRIPTS.md` is generated. This avoids importing a project full of `Script is missing` errors. |
| Backup before install | Every file that will be overwritten is backed up to `<Toolkit>\_PackToolBackup\<timestamp>\`, so you can roll back. |
| Protect healthy files | During installation, a file is replaced only if the new version has fewer dangling references or the existing file is a stale leftover. Healthy project assets are left untouched. |
| Version self-check | The tool verifies the export again and reports the match rate and number of missing references. |

## 5. Caveats

- Use the same Toolkit version as the mod author. Otherwise, script classes and GUIDs may not match and parts can be broken. This is the real cause behind many “everything is Missing after import” reports; the tool cannot fix a version mismatch.
- Do not force-install when the tool reports that some scripts could not be linked. Switch to a matching Toolkit version and try again.
- If parts are still black or Missing, run `Assets → Refresh` (or reopen the project) so Unity can re-import the assets, then run Odin again.
- If textures become broken again after being fixed, rerun **One-click export** with **Install into Toolkit** enabled.
- The tool does not automatically delete orphan files (for example, textures that are no longer referenced). They are harmless, and keeping them is safer.

## 6. System requirements

- Windows 10 / 11 x64
- No Python installation required; distributed as a single-file EXE, approximately 55 MB
- AssetRipper 1.1.4 is bundled, so exporting does not require an internet connection. The runtime is extracted to `AssetRipper-1.1.4\` beside the EXE; if that location is not writable, the user's local application-data directory is used instead.
- An “Unknown publisher / SmartScreen” warning on first launch may appear because the signing certificate is not in Windows' built-in trusted root store.
- Settings are stored in `%APPDATA%\AFuturestar\SFS-Pack-Tool\settings.json`.

## 7. Miscellaneous

- **Tutorial** in the top menu opens the illustrated usage guide bundled with the app; it works offline.
- **About the author** shows author information and the QQ group link.
- **About this app** explains the tool's purpose and implementation.
- License: GPL-3.0 (because AssetRipper is bundled). See `GPL_COMPLIANCE.md`.

## Contact

- Author: A Future star (localization / maintenance)
- QQ group: 923038827 · [Join the QQ group](https://qm.qq.com/q/3NAzgXluEo)
- When reporting an issue, please include the `mod.pack` filename, your Toolkit version, and the output from the tool's log window.

---

# 中文

## 一、这个工具解决什么问题

SFS 的模组包 `.pack` 里包含 Unity 资源包（prefab、贴图、材质、音效）和可选的自定义脚本 DLL。要修改、使用它，或者把它做成自己的零件，需要先将其转换成可打开的 Unity 工程。但使用官方 AssetRipper 导出的工程，往往会出现大量问题：

- 脚本引用找不到类 → 满屏 `Script is missing`
- 贴图 / 材质引用找不到目标 → Odin 报出成百上千条 `reference has gone missing`
- 零件渲染成一整块黑板（而且不报错）
- 渲染脚本 `RenderSortingModule.SetDepth` 抛出 `NullReferenceException`

这个工具可以一次性处理这些问题：解包、对齐、修复、合并、装机，一条龙完成。

**一句话：让 mod 零件在 Toolkit 里正常加载，不再挂空。**

## 二、功能总览

| 功能 | 说明 |
| --- | --- |
| 汉化 | 提取待翻译文本 → 翻译 JSON → 写回并生成中文包 |
| 包信息 | 查看包内的平台、零件数量，以及是否包含自定义脚本 |
| 剥离 | 只保留目标平台，大幅减小 `.pack` 体积 |
| 一键导出 | 将 `.pack` 转换为可直接打开的 Unity 工程，全流程自动化 |
| 脚本免挂 | 自动将 prefab 的脚本引用对齐到 Toolkit 的真实脚本 |
| 修复黑板 | 零件渲染成黑板时，自动将占位着色器替换回真实着色器 |
| 修复悬空引用 | 贴图 / 材质 / 音效引用丢失时，按名称重新链接或补回 |
| 资产归拢 | 将模组自带资产按类型归类到 `Assets/<模组名>/` |
| 合并包 | 只选取 Toolkit 中缺少的零件，生成干净的合并包 |
| 并入 Toolkit | 直接安装到工程；安装前备份，不覆盖已有的正常文件 |

界面顶部提供「中文 / English」切换，界面和日志均支持中英文。

## 三、用法详解

### 1）汉化

1. 点击「选择原始 mod.pack」。
2. 点击「提取待翻译文本」，生成 `texts_to_translate.json`（输出路径可自选，默认与源包在同一目录）。
3. 打开 JSON 进行翻译，格式为 `{ "原文": "译文" }`，只需填写实际修改的条目。
4. 点击「选择翻译 JSON」，再点击「写入汉化并生成 Pack」，输出 `mod_CN.pack`。
5. 「汉化作者标识」会追加到资源的 `Author` 字段，默认值为 `〈A Future star汉化〉`。

工具内置过滤机制，不会随意修改内部变量名：包含 38 个词的黑名单（`Toggle`、`Metal`、`mass` 等）和 16 个字段的白名单（`DisplayName`、`Description` 等），只处理真正面向用户显示的文本。

### 2）包信息 / 剥离

- **包信息：** 检查 Windows / Android / Mac / iOS 平台是否齐全、零件数量，以及是否包含 `CodeAssembly`（自定义脚本）。零件数根据 prefab 根对象统计，避免虚高。
- **剥离：** 选择目标平台后，生成只包含该平台的 `.pack`，体积更小。若包内没有目标平台，或输出路径与源文件相同，工具会拒绝执行，以免覆盖原包。

### 3）一键导出到 Toolkit（核心功能）

1. 点击「选择工程目录」——需要选择两个目录：
   - 首先选择 Modding Toolkit 根目录（包含 `Assets/Scripts`）。
   - 然后选择原始 mod 工程目录（可选，但强烈建议填写，以便自动修复悬空引用）。
2. 勾选「导出后并入 Toolkit」。不勾选则只生成合并包，不会修改现有工程。
3. 点击「一键导出工程」，等待程序自动完成。

工具会依次执行：

```text
解包前扫描包信息
  → AssetRipper 解包
  → 脚本免挂对齐
  → 空壳着色器修复
  → 模组资产归拢
  → 生成合并包
  → 并入 Toolkit（可选）
  → 导出后自检
```

导出产物位于 `%TEMP%\SFS_Pack_Stage\<包名>_export\`（临时目录，可在不需要时删除）。

### 4）修复 Toolkit

「修复 Toolkit 空壳着色器·悬空引用」按钮用于修复已经损坏的工程：

- 清理混入工程的 AssetRipper 空壳着色器（黑板问题的根源）。
- 扫描全工程中指向不存在 GUID 的引用，并按名称补回或重新指向资源。
- 无法找到来源的资源会列入 `_PackToolBackup\<时间戳>_dangling\dangling_manifest.txt`，供人工处理。

> 如需自动修复，必须填写「原始 mod 工程目录」。如果不填写，工具只会扫描，不会修改文件。

## 四、重要的保护机制

| 机制 | 说明 |
| --- | --- |
| 合并闸门 | 只要有脚本引用无法解析，就会拒绝合并、弹窗列出类名，并生成 `UNRESOLVED_SCRIPTS.md`，避免将大量 `Script is missing` 错误带入工程。 |
| 装机前备份 | 所有将被覆盖的文件都会先备份到 `<Toolkit>\_PackToolBackup\<时间戳>\`，方便回滚。 |
| 不覆盖正常文件 | 只有新版本的悬空引用更少，或现有文件属于历史残留时才会替换；工程中正常的资源不会被修改。 |
| 版本自检 | 导出后自动复查，并报告匹配率和缺失数量。 |

## 五、注意事项

- Toolkit 版本应与 mod 作者使用的版本一致。否则脚本类和 GUID 可能无法对应，导致零件挂空。这是许多「导入后一片 Missing」问题的真正原因，工具无法替你解决版本不匹配。
- 如果提示「有脚本没接上」，不要强行安装。请换成匹配的 Toolkit 版本后重试。
- 如果零件仍然显示为黑板或 Missing，先执行 `Assets → Refresh`（或重新打开工程），让 Unity 重新导入，再重新运行 Odin。
- 如果修复后的贴图再次丢失，勾选「并入 Toolkit」并重新运行「一键导出工程」。
- 工具不会自动删除孤儿文件（例如没有被引用的贴图）。这些文件通常无害，保留更安全。

## 六、系统要求与环境

- Windows 10 / 11 x64
- 无需安装 Python，单文件 EXE，约 55 MB
- 已内置 AssetRipper 1.1.4，导出时无需联网。运行组件默认释放到 EXE 同目录的 `AssetRipper-1.1.4\`；若该目录不可写，则使用用户本地应用数据目录。
- 首次运行可能提示「发布者未知 / SmartScreen」，这是因为签名证书不在 Windows 内置的受信任根证书中。
- 设置保存在 `%APPDATA%\AFuturestar\SFS-Pack-Tool\settings.json`。

## 七、其他

- 顶部菜单「教程」：打开程序内置的图文使用说明，可离线查看。
- 顶部菜单「关于作者」：查看作者信息和 QQ 群入口。
- 顶部菜单「关于应用」：查看工具用途与实现思路。
- 许可协议：GPL-3.0（因程序内置 AssetRipper），详见 `GPL_COMPLIANCE.md`。

## 关于

- 作者：A Future star（汉化 / 维护）
- QQ 群：923038827 · [加入 QQ 群](https://qm.qq.com/q/3NAzgXluEo)
- 反馈问题时请附上 `mod.pack` 文件名、Toolkit 版本，以及程序日志窗口中的输出。
