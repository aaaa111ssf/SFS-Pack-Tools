# SFS Pack Tool — 工具介绍 / User Guide

**V2.3.2** · 作者 / Author: **A Future star** · QQ 群 / Group: **923038827**

**语言 / Language：** [🇨🇳 中文](#中文) ｜ [🇬🇧 English](#english)

---

## 中文

### 一、这个工具解决什么问题

SFS 的模组包 `.pack` 里塞的是 Unity 资源包（prefab、贴图、材质、音效）和可选的
自定义脚本 DLL。要改它、用它，或者把它做成自己的零件，就得先把它变成能打开的
**Unity 工程**——而这一步用官方 AssetRipper 直接做出来的工程，**零件基本全是挂的**：

- 脚本引用找不到类 → 满屏 `Script is missing`
- 贴图 / 材质引用找不到目标 → Odin 报成百上千条 `reference has gone missing`
- 零件渲成一整块**黑板**（而且不报错）
- 渲染脚本 `RenderSortingModule.SetDepth` 抛 `NullReferenceException`

**这个工具就是把这些坑一次性填平**：解包、对齐、修复、合并、装机，一条龙。

一句话：**让 mod 零件在 Toolkit 里不挂。**

### 二、功能总览

| 功能 | 说明 |
| --- | --- |
| **汉化** | 提取待翻译文本 → 翻译 JSON → 写回生成中文包 |
| **包信息** | 看包里有几个平台、多少个零件、带不带自定义脚本 |
| **剥离** | 只保留目标平台，`.pack` 体积大幅减小 |
| **一键导出** | 把 `.pack` 解成可直接打开的 Unity 工程（全流程自动） |
| **脚本免挂** | 自动把 prefab 的脚本引用对齐到 Toolkit 真脚本 |
| **修黑板** | 零件渲成一整块黑板？自动换回真着色器 |
| **修悬空** | 贴图 / 材质 / 音效引用丢失，自动按名补回或重定向 |
| **资产归拢** | 模组自带的资产自动归到 `Assets/<模组名>/` 下分类摆放 |
| **合并包** | 只挑 Toolkit 没有的零件，生成一个干净的合并包 |
| **并入 Toolkit** | 直接装进工程，装之前先备份，不覆盖你已有的正常文件 |

界面顶部有「中文 / English」切换，整体界面和日志都有中英双语。

### 三、用法详解

#### 1）汉化（原 v20 就有的功能）

1. 点「选择原始 mod.pack」
2. 点「提取待翻译文本」→ 生成 `texts_to_translate.json`（输出路径可自选，默认跟源包同目录）
3. 打开 JSON 翻译。格式是 `{ "原文": "译文" }`，**只写改过的条目即可**
4. 点「选择翻译 JSON」→ 点「写入汉化并生成 Pack」，输出 `mod_CN.pack`
5. 「汉化作者标识」那一栏会追加到资源的 `Author` 字段（默认 `〈A Future star汉化〉`）

工具自带过滤，不会去动内部变量名：黑名单 38 个词（`Toggle`、`Metal`、`mass`…）
加上一张 16 个字段的**白名单**（`DisplayName`、`Description`…），只挑真正给人看的文本。

#### 2）包信息 / 剥离

- **包信息**：报告各平台（Windows / Android / Mac / iOS）是否齐全、一共多少个零件、
  带不带 `CodeAssembly`（自定义脚本）。零件数是**按 prefab 根对象**统计的，不会虚高。
- **剥离**：选一个目标平台 → 生成只含该平台的 `.pack`，体积能小一大截。
  两处保护：目标平台不在包里会**直接拒绝**；输出路径和源文件相同也会拒绝（防覆盖原包）。

#### 3）一键导出到 Toolkit（主力功能）

1. 点「选择工程目录」——这个按钮一次选两个：
   - 先选 **Modding Toolkit 根目录**（含 `Assets/Scripts`）
   - 再选 **原始 mod 工程目录**（可选，但**强烈建议选**，用来自动修复悬空引用）
2. 勾上「导出后并入 Toolkit」（不勾就只生成合并包，不碰你的工程）
3. 点「一键导出工程」，然后就不用管了

工具会自动依次完成：

```
解包前扫描包信息  →  AssetRipper 解包  →  脚本免挂对齐  →  空壳着色器修复
  →  模组资产归拢  →  生成合并包  →  并入 Toolkit（可选）  →  导出后自检
```

**导出产物在** `%TEMP%\SFS_Pack_Stage\<包名>_export\`（临时目录，可随时删）。

#### 4）修复 Toolkit

按钮「修复 Toolkit 空壳着色器·悬空引用」，用于收拾**已经被弄坏**的工程：

- 清理混进去的 AssetRipper 空壳着色器（黑板根因）
- 扫描全工程指向**不存在 GUID** 的引用，并按名补回 / 重定向
- 找不到出处的会写清单到 `_PackToolBackup\<时间戳>_dangling\dangling_manifest.txt` 交人工处理

> 想让它**自动修**，就得填上「原始 mod 工程目录」。不填的话它**只扫描、绝不改你的文件**。

### 四、几个重要的保护机制

| 机制 | 说明 |
| --- | --- |
| **合并闸门** | 只要有脚本引用接不上，**拒绝合并**并弹窗列出类名，同时写出 `UNRESOLVED_SCRIPTS.md`。宁可停在合并包，也不把满屏 `Script is missing` 灌进你的工程 |
| **装机前先备份** | 所有被覆盖的文件都会先备份到 `<Toolkit>\_PackToolBackup\<时间戳>\`，随时可回滚 |
| **不覆盖正常文件** | 并入时只在「新版本挂空更少」或「同名文件是历史残留」时才替换，你工程里正常的资源一律不碰 |
| **版本自检** | 导出后自动复查，报告命中率和缺失数 |

### 五、注意事项

- **Toolkit 版本要和 mod 作者一致。** 版本对不上，脚本类和 GUID 全对不上，零件必然挂空
  ——这是绝大多数「导入完一片 Missing」的真正原因，工具无法替你解决。
- **弹出「有脚本没接上」时不要硬装。** 换个版本的 Toolkit 再来。
- **还是黑板 / 还是 Missing？** 先 `Assets → Refresh`（或重开工程）让 Unity 重新导入，
  再重跑一次 Odin。
- **贴图之前修好了又挂？** 直接用「一键导出工程」+ 勾「并入 Toolkit」重跑一遍，会自愈。
- **工具不自动删孤儿文件**（GUID 没人引用的贴图等）。它们无害，留着更安全。

### 六、系统要求与环境

- **Windows 10 / 11 x64**
- **无需安装 Python**，单文件 EXE，约 55 MB
- 已内置 **AssetRipper 1.1.4**，**导出时不需要联网**
  （运行包会释放到 EXE 同目录的 `AssetRipper-1.1.4\`；没有写入权限则用用户本地应用数据目录）
- 第一次运行可能提示「发布者未知 / SmartScreen」，属正常（签名证书不在 Windows 预置信任根里）
- 界面设置保存在 `%APPDATA%\AFuturestar\SFS-Pack-Tool\settings.json`

### 七、其它

- 顶部菜单 **「教程」** = 图文使用说明（已内置在程序里，离线可看）
- 顶部菜单 **「关于作者」** = 作者信息与 QQ 群入口
- 顶部菜单 **「关于应用」** = 工具用途与实现思路
- 许可：**GPL-3.0**（因内置 AssetRipper），详见 `GPL_COMPLIANCE.md`

### 关于

- 作者：**A Future star**（汉化 / 维护）
- QQ 群：**923038827** · <https://qm.qq.com/q/3NAzgXluEo>
- 反馈问题时请附上：`mod.pack` 名称、Toolkit 版本、程序日志窗口里的输出

---

## English

### 1. What this tool solves

An SFS mod pack (`.pack`) contains Unity asset bundles (prefabs, textures, materials, audio)
plus an optional custom-script DLL. To edit it, use it, or rebuild it into your own parts,
you first need a real **Unity project** — and a project produced by the official AssetRipper
has **almost everything broken**:

- Script references can't resolve → a wall of `Script is missing`
- Texture / material references are dangling → hundreds of Odin `reference has gone missing` errors
- Parts render as a **solid black board** (with no error at all)
- `RenderSortingModule.SetDepth` throws `NullReferenceException`

**This tool fills all those potholes at once**: unpack, align, repair, merge, install.

In one line: **make mod parts load in the Toolkit with nothing missing.**

### 2. Feature overview

| Feature | Description |
| --- | --- |
| **Localization** | Extract translatable text → translate the JSON → write it back into a localized pack |
| **Pack info** | See which platforms the pack has, how many parts, whether custom scripts are bundled |
| **Strip** | Keep only the target platform — the `.pack` shrinks a lot |
| **One-click export** | Turn the `.pack` into a Unity project you can just open (fully automated) |
| **Script alignment** | Rewrites prefab script references to the Toolkit's real scripts |
| **Black-board fix** | Parts rendering as a solid black board? Swaps the placeholder shader back for the real one |
| **Dangling-ref repair** | Missing texture / material / audio references are re-linked or copied back by name |
| **Asset grouping** | Mod-owned assets are filed under `Assets/<mod name>/` by type |
| **Merge package** | Builds a clean merge package containing only what your Toolkit lacks |
| **Install into Toolkit** | Installs straight into your project — with a backup first, and your healthy files left alone |

The UI has a **中文 / English** switch at the top; the interface and the log are bilingual.

### 3. Usage

#### 3.1 Localization

1. Click **Select source mod.pack**
2. Click **Extract text** → produces `texts_to_translate.json` (output path configurable; defaults next to the source pack)
3. Translate the JSON. Format is `{ "original": "translation" }` — **only include entries you actually changed**
4. Click **Select translation JSON**, then **Write localization & build pack** → outputs `mod_CN.pack`
5. The **Translator tag** field is appended to the asset's `Author` field (default `〈A Future star汉化〉`)

Built-in filtering keeps it away from internal identifiers: a 38-word blacklist
(`Toggle`, `Metal`, `mass`, …) plus a 16-field **whitelist** (`DisplayName`, `Description`, …),
so only genuinely user-facing text is touched.

#### 3.2 Pack info / Strip

- **Pack info**: reports whether each platform (Windows / Android / Mac / iOS) is present,
  how many parts there are, and whether a `CodeAssembly` (custom scripts) is bundled.
  The part count is derived from **prefab root objects**, so it isn't inflated.
- **Strip**: pick a target platform → produces a `.pack` containing only that platform,
  much smaller. Two guards: it refuses if the target platform isn't in the pack, and it refuses
  if the output path equals the source file (so your original pack can't be overwritten).

#### 3.3 One-click export into the Toolkit (the main feature)

1. Click **Select project dirs** — this one button asks for two things:
   - First the **Modding Toolkit root** (containing `Assets/Scripts`)
   - Then the **original mod project directory** (optional, but **strongly recommended** — it's what enables automatic dangling-reference repair)
2. Tick **Install into Toolkit after export** (leave it off to only build a merge package without touching your project)
3. Click **One-click export** and you're done

The tool then runs the whole chain by itself:

```
scan the pack  →  AssetRipper export  →  script alignment  →  stub-shader fix
  →  mod-asset grouping  →  build merge package  →  install into Toolkit (optional)  →  post-export self-check
```

**Output lands in** `%TEMP%\SFS_Pack_Stage\<pack name>_export\` (a temp directory — safe to delete).

#### 3.4 Repair the Toolkit

The **Repair Toolkit (stub shaders · dangling refs)** button cleans up a project that has
**already been damaged**:

- Removes AssetRipper placeholder shaders that crept in (the black-board root cause)
- Scans the whole project for references to **non-existent GUIDs** and re-links or copies them back by name
- Ones with no recoverable source are listed in `_PackToolBackup\<timestamp>_dangling\dangling_manifest.txt` for manual review

> For it to repair automatically you must supply the **original mod project directory**.
> Without it, it **only scans — it will never modify your files**.

### 4. Safety mechanisms

| Mechanism | Description |
| --- | --- |
| **Merge gate** | If any script reference can't be resolved it **refuses to merge**, shows a popup listing the class names, and writes `UNRESOLVED_SCRIPTS.md`. It would rather stop at the merge package than flood your project with `Script is missing` |
| **Backup before install** | Every file it overwrites is first backed up to `<Toolkit>\_PackToolBackup\<timestamp>\` — always rollback-able |
| **Never overwrites healthy files** | On install it only replaces a file when the new version has fewer dangling refs, or when the existing file is a stale left-over. Your healthy assets are never touched |
| **Version self-check** | After export it re-verifies and reports the hit rate and missing counts |

### 5. Caveats

- **Use the same Toolkit version as the mod author.** Otherwise script classes and GUIDs won't
  line up and parts will inevitably be broken — this is the real cause behind most
  "everything is Missing after import" reports, and the tool can't fix it for you.
- **Don't force-install when it says "some scripts couldn't be linked."** Switch to a matching
  Toolkit version and try again.
- **Still black / still Missing?** Run `Assets → Refresh` (or reopen the project) so Unity
  re-imports, then re-run Odin.
- **Textures broke again after being fixed?** Just re-run **One-click export** with
  **Install into Toolkit** ticked — it self-heals.
- **It never auto-deletes orphan files** (textures nothing references). They're harmless;
  leaving them in place is safer.

### 6. System requirements

- **Windows 10 / 11 x64**
- **No Python required** — single-file EXE, ~55 MB
- **AssetRipper 1.1.4 is bundled** — **no internet needed** to export
  (the runtime is extracted next to the EXE into `AssetRipper-1.1.4\`; if that location isn't
  writable it falls back to the user's local app-data folder)
- An "Unknown publisher / SmartScreen" warning on first run is normal
  (the signing certificate isn't in Windows' built-in trust store)
- Settings are stored in `%APPDATA%\AFuturestar\SFS-Pack-Tool\settings.json`

### 7. Misc

- Top menu **Tutorial** = illustrated usage guide (bundled inside the app, works offline)
- Top menu **About the author** = author info and QQ group link
- Top menu **About this app** = what the tool is for and how it works
- License: **GPL-3.0** (because AssetRipper is bundled) — see `GPL_COMPLIANCE.md`

### Contact

- Author: **A Future star** (localization / maintenance)
- QQ group: **923038827** · <https://qm.qq.com/q/3NAzgXluEo>
- When reporting an issue, please include: the `mod.pack` name, your Toolkit version,
  and the tool's log output
