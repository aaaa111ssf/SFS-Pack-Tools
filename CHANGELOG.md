# 更新日志 / Changelog

本文档同时提供中文与英文两种表述，两侧内容一一对应 / This document is written in
Chinese and English side by side; both versions carry the same content.

格式沿用 Keep a Changelog，版本号遵循语义化版本 / Format follows Keep a Changelog,
versions follow semantic versioning.

---

## v2.3.6-PyQt — 2026-10-26

### 中文

本版补齐 **SFS 1.7（Propulsion-Rebase）** 支持，并修掉导入 1.6 mod 时两个会导致
"部件 Missing Script / 燃料不互通"的真问题。

#### 新增

| 能力 | 说明 |
| --- | --- |
| **1.7 引擎自动修复（实验）** | 设置 → 高级 → 「实验：1.7 引擎自动修复」。导出管线 **1.86 步**为旧 mod 的引擎/助推器补齐 1.7 新增的 `[Required]` 字段：`EngineModule` 补 `heatHitbox` / `isVacuum` / `multipleNozzles` / `heatHitboxes[]`；`BoosterModule` 补 `heatHitbox` / `setDensity` / `boosterOn` |
| **安全边界** | 仅当目标 Toolkit 真的是 1.7（`EngineModule.cs` 含 `heatHitbox`）才执行，否则 `skip=not_17_toolkit`；**幂等**（已有有效 heatHitbox 跳过）；改前备份到 `<导出>/_ENGINE17_BACKUP` |
| **`heatHitbox` 解析** | 引擎 = heatHolder 的第一个子物体；助推器 = heatHolder **自身**（与 1.7 `BoosterModule.Start` 的兜底 `heatHitbox = heatHolder` 一致，实测 1.7 `BoosterBase.prefab` 的 holder 本身就叫 "Heat Hitbox"） |
| **目标框架探测** | `detect_target_framework()` 读程序集的 `TargetFrameworkAttribute`，写入 `scan_pack()['code_assembly']['target_framework']` 供参考 |

#### 修复

| 问题 | 根因与改法 |
| --- | --- |
| **导入后部件 Missing Script** | Unity 把 `Assets` 内所有 `.dll` 当托管插件；`Assets/ModBuilder/xxx_CodeAssembly.dll` 与 `Assets/Plugins/<程序集>.dll` 同名 → 「同名程序集」冲突，Unity 卸载其一。改为把 CodeAssembly 写到 `<Toolkit>/_PackToolCodeAssembly/`（**Assets 之外**），并自动迁移旧版遗留在 `Assets/ModBuilder` 的副本（仅与 Plugins 字节完全相同才移动，否则只告警） |
| **1.6 燃料不挂到原版（`<模组名>_Liquid_Fuel`）** | `_norm_asset_text` 原先只忽略 `plainText: 0`；1.6 包导出燃料带 `plainText: 1`，与 1.5 时代无此字段的原版不等价 → 被判成"改过的燃料"保留私有副本。改为忽略**任意取值**的 `plainText:` 行（只影响显示译法，不改变资源身份） |

#### 验证

| 项目 | 结果 |
| --- | --- |
| `test_core_smoke.py` | 全量 ALL PASS |
| 1.7 修复用例（2h） | 正例 / 幂等 / 非 1.7 跳过 / 助推器指向自身 —— 全过 |
| 真实 1.6 `Engine Frontier` | 迁移后 `heatHitbox` 与 1.7 原版完全一致 |

---

### English

This release adds **SFS 1.7 (Propulsion-Rebase)** support and fixes two real problems that
caused missing scripts and non-interoperable fuel when importing 1.6 mods.

#### Added

| Capability | Detail |
| --- | --- |
| **1.7 engine auto-repair (experimental)** | Settings → Advanced → "1.7 engine auto-repair". Export step **1.86** backfills the `[Required]` fields 1.7 introduced: `EngineModule` gets `heatHitbox` / `isVacuum` / `multipleNozzles` / `heatHitboxes[]`; `BoosterModule` gets `heatHitbox` / `setDensity` / `boosterOn` |
| **Safety guard** | Runs only when the Toolkit really is 1.7 (`EngineModule.cs` contains `heatHitbox`), otherwise `skip=not_17_toolkit`; **idempotent**; backs up to `<export>/_ENGINE17_BACKUP` |
| **`heatHitbox` resolution** | Engine = heatHolder's first child; booster = heatHolder **itself** (matching 1.7 `BoosterModule.Start`'s `heatHitbox = heatHolder`) |
| **Target framework probe** | `detect_target_framework()` records the assembly's `TargetFrameworkAttribute` into `scan_pack()['code_assembly']['target_framework']` for reference |

#### Fixed

| Problem | Root cause and fix |
| --- | --- |
| **Missing Script after import** | Unity imports every `.dll` under `Assets` as a managed plugin; a duplicate of the same assembly in `Assets/ModBuilder` and `Assets/Plugins` triggers a same-name conflict and one copy is unloaded. CodeAssembly is now written to `<Toolkit>/_PackToolCodeAssembly/` (**outside Assets**), and stale copies under `Assets/ModBuilder` are relocated when byte-identical |
| **1.6 fuel not redirected to stock** | `_norm_asset_text` only ignored `plainText: 0`; 1.6 packs export `plainText: 1`. Now any `plainText:` value is ignored — display-only, does not change asset identity |

#### Verification

| Item | Result |
| --- | --- |
| `test_core_smoke.py` | ALL PASS |
| 1.7 repair cases (2h) | positive / idempotent / non-1.7 skip / booster self — all pass |
| Real 1.6 `Engine Frontier` | `heatHitbox` after migration matches 1.7 exactly |

---

## v2.3.5-PyQt — 2026-10-23

### 中文

界面从 **Tkinter 整体换成 PyQt5 + SiliconUI**。功能和操作流程一条没变，变的是长相与手感。

#### 界面

| 变化 | 说明 |
| --- | --- |
| **深色 SiliconUI 主题** | 圆角卡片、立体底面、按压回弹、hover 高亮，配色直接取 SiliconUI 的 `DarkColorGroup`，不会出现两套灰互相打架 |
| **左侧导航 + 三页布局** | 还原 / 汉化 / 剥离 各占一页，底部常驻日志区；窗口拉小时页面滚动，不会把卡片压扁叠字 |
| **Fluent 图标** | 导航、按钮、弹窗都用内置图标包（`ic_fluent_*`），比纯文字好认 |
| **统一的深色弹窗** | 提示/询问/错误、设置页、回滚、清理缓存全部自绘圆角对话框；不再弹刺眼的白底系统框 |
| **系统标题栏跟随深色** | 走 DWM `DWMWA_USE_IMMERSIVE_DARK_MODE`，Win10 1809+ / Win11 都是深色标题栏 |
| **原生文件对话框** | 选择 pack / JSON / 目录 / 多选批量，都用系统对话框（支持路径记忆、多选、中文路径） |
| **切语言立即生效** | 点右上角语言按钮当场重排文案，不用重启；任务运行中也不会被打断 |

#### 结构

- 业务逻辑（导出工程、并入 Toolkit、剥离、提取/写回、回滚、预览、批量、探测、清理缓存）
  全部抽到 **`sfs_pack_tool_logic.py`**，一个 GUI 依赖都不 import。
- 原 Tkinter 界面移到 `legacy/sfs_pack_tool_gui_tk.py` 留档，两边共用同一份逻辑，
  不会再出现"改了一边忘了另一边"。
- `sfs_pack_tool_gui.py` 现在是纯界面层（PyQt5 + SiliconUI），入口 `main()` 不变。

#### 打包

- 新增依赖：`PyQt5==5.15.11`、`PyQt-SiliconUI`（GPL-3.0，已随仓库内置在 `siui/`）、`numpy`、`python-dateutil`、`pyperclip`。
- spec 里补了 `siui` 的图标包数据与子模块收集，否则 EXE 里的图标会全部消失。
- **EXE 体积明显变大**（Qt 运行时 + numpy），这是换框架的直接代价。

#### 验证

| 项目 | 结果 |
| --- | --- |
| `test_core_smoke.py` | 192 项 ALL PASS |
| 界面冒烟（弹窗 / 切语言 / 忙碌锁 / 进度条 / 日志着色 / 异步任务） | 全部通过，逐页截图人工核对 |

### English

The UI moved from **Tkinter to PyQt5 + SiliconUI**. Nothing about the workflow changed —
only how it looks and feels.

#### Interface

| Change | Detail |
| --- | --- |
| **Dark SiliconUI theme** | Rounded cards, raised surfaces, press-shrink feedback and hover highlights; colours come straight from SiliconUI's `DarkColorGroup` so there aren't two competing greys |
| **Sidebar + three pages** | Restore / Localise / Strip each get a page, with a persistent log panel underneath; shrinking the window scrolls instead of squashing cards into overlapping text |
| **Fluent icons** | Navigation, buttons and dialogs use the bundled icon pack (`ic_fluent_*`) |
| **Consistent dark dialogs** | Info / question / error, settings, rollback and cache-cleanup are all custom rounded dialogs — no more blinding white system boxes |
| **Dark native title bar** | Via DWM `DWMWA_USE_IMMERSIVE_DARK_MODE` on Win10 1809+ / Win11 |
| **Native file dialogs** | System pickers for packs, JSON, folders and multi-select batches (path memory, multi-select, non-ASCII paths) |
| **Instant language switch** | The language button relabels everything immediately; a running task is never interrupted |

#### Structure

- All business logic (export, merge into Toolkit, strip, extract/write-back, rollback,
  preview, batch, probe, cache cleanup) now lives in **`sfs_pack_tool_logic.py`**, which
  imports no GUI toolkit at all.
- The old Tkinter UI is kept for reference at `legacy/sfs_pack_tool_gui_tk.py`; both
  front-ends share the same logic, so they cannot drift apart.
- `sfs_pack_tool_gui.py` is now purely the PyQt5 + SiliconUI layer; `main()` is unchanged.

#### Packaging

- New dependencies: `PyQt5==5.15.11`, `PyQt-SiliconUI` (GPL-3.0, vendored in `siui/`),
  `numpy`, `python-dateutil`, `pyperclip`.
- The spec now collects the SiliconUI icon pack data and submodules — without it every
  icon disappears inside the EXE.
- **The EXE got noticeably larger** (Qt runtime + numpy): that is the direct cost of the switch.

#### Verification

| Item | Result |
| --- | --- |
| `test_core_smoke.py` | 192 checks, ALL PASS |
| UI smoke (dialogs / language switch / busy lock / progress / log colouring / async) | all pass, every page checked by screenshot |

---

## v2.3.5 — 2026-10-23

### 中文

本版把 `feature/missing-functions` 分支的 10 项能力并入主线，并**修掉复审中发现的 5 个真 bug**。

#### 新增能力

| 能力 | 说明 |
| --- | --- |
| **多自定义脚本模组共存** | 程序集内部名按模组名 CRC32 派生成等长的 `CodeAsm_xxxx`，原地改写 PE 元数据。两个带 dll 的模组从此能装进同一份 Toolkit（此前后者会静默顶掉前者） |
| **一键回滚** | `_PackToolBackup` 终于有还原入口：默认只预演，确认才写；回滚前先把现状再备份一份 |
| **合并前预览 / 差异报告** | 导入前先看会新增/替换/跳过哪些文件 |
| **批量导出** | 选多个 `.pack` 逐个导出，单项失败不中断，结束汇总 |
| **Toolkit 版本探测** | Unity 版本 + Toolkit 版本 + `Assets/Scripts` 指纹；指纹变了说明换过版本 |
| **AssetRipper 版本可选** | 设置页可选内置版 / 指定版本 / 手动指定 exe |
| **日志落盘 + 诊断报告** | 日志写 `%APPDATA%/AFuturestar/SFS-Pack-Tool/logs/`，关窗生成可分享的 `_report.md` |
| **稳健 UnityYAML 解析** | 取代单行正则：字段乱序、block style、guid 带引号、无空格都能正确替换（旧正则静默失配 → replace 0 次却没人报错） |
| **增量重导出** | 包指纹 + Toolkit 指纹 + 部件仍在 → 可跳过 |
| **CLI 与 GUI 对齐** | `--overwrite` 真正生效、`-i` 多文件、`--preview` / `--backups` / `--restore` / `--probe` |

#### 新增设置页（菜单栏「设置」）

把占地方又用得少的东西收进去：**AssetRipper 版本选择**、日志目录/保留天数、增量导出开关、
Toolkit 版本探测。**改完点「应用」才生效**，点「取消」或直接关窗不保存任何改动
（这些项改错会让导出直接失败，必须留一条回头路）。

#### 复审发现并修掉的 bug

1. **PE 行宽按错规则算（最严重）**：`sfs_assembly_rename._row_size` 把复合（coded）索引
   当成单表索引算宽度。`CustomAttribute` 的 `HasCustomAttribute` 是 5 位 coded 索引
   （阈值 2048），真实大程序集需要 4 字节，它按 2 字节算 → 表偏移漂移 →
   读出的程序集内部名是空串。实测 `Assembly-CSharp.dll`（1.2 MB）读不出名字，
   小 dll（ilspycmd，方法数未越阈值）碰巧通过。现已按 ECMA-335 全部重写，
   实测 `Assembly-CSharp` / `UnityEngine` / `ilspycmd` 均正确。
2. **空名会被当成合法文件名**：紧接上一条，空名会让落位变成 `Assets/Plugins/.dll`
   （Unity 根本认不出的插件）。现在 `read_assembly_name` 遇空名抛异常，
   `_unique_assembly_for_mod` 遇空名退回原名。
3. **增量导出永远不生效**：`record_export()` 的 `parts` 要的是**部件名列表**，
   调用处传了数量（int）还多传一个不存在的 `installed` 关键字 → TypeError 被
   吞掉 → 索引文件从未生成 → 每次都判「首次导出」。已改为按导出工程收集部件名。
4. **AssetRipper 版本选择必然失败**：GUI 一律传 `no_download=True`（为内置版设计），
   而版本分支会跳过内置版 → 用户一改版本，导出直接报错。现在只在用户显式指定
   版本/路径时才允许下载；且填与内置版相同的版本号会直接复用内置版，不再要求下载。
5. **诊断报告永不生成**：`DiagnosticLog.close()` 从没被调用过，日志文件有、报告没有。
   现在关窗时收尾并写入输入包 / Toolkit 摘要。

#### 其它

- 设置窗口居中到主窗口（原先贴屏幕左上角，说明文字被切）。

#### 验证

| 测试 | 结果 |
| --- | --- |
| `test_core_smoke.py` | 192 项 ALL PASS |
| `test_custom_scripts.py` / `test_dedupe_cs0101.py` | 39 / 20 通过 |
| `test_unity_yaml.py` | 43 通过 |
| `test_multi_assembly.py` / `test_two_mods_coexist.py` | 24 / 19 通过 |
| `test_toolbox.py` / `test_cli.py` / `test_round2.py` | 58 / 27 / 30 通过 |
| GUI 冒烟（设置页草稿语义 / 增量闭环 / 诊断报告） | 15 项通过 |

合计 **467 项**专项 + 原有回归，全部通过。多模组共存端到端实测：
A、B 两个带 dll 的模组在同一 Toolkit 里分别落成 `CodeAsm_0c44.dll` 与
`CodeAsm_5dfe.dll`，引用各自可解析。

### English

This release merges the 10 capabilities from `feature/missing-functions` into main
and **fixes the 5 real bugs found while reviewing the port**.

#### New capabilities

| Capability | Notes |
| --- | --- |
| **Custom-script mods can coexist** | Assembly identity is rewritten in place to an equal-length `CodeAsm_xxxx` derived from the mod name (CRC32). Two mods that both ship a dll now fit in one Toolkit (previously the second silently replaced the first) |
| **One-click rollback** | `_PackToolBackup` finally has a restore path: preview by default, write only after confirmation, and the current state is backed up first |
| **Pre-merge preview / diff report** | See what will be added / replaced / skipped before importing |
| **Batch export** | Pick several `.pack` files; one failure does not abort the batch; summary at the end |
| **Toolkit version probe** | Unity version + Toolkit version + an `Assets/Scripts` fingerprint (a changed fingerprint means a different Toolkit build) |
| **AssetRipper version selectable** | Settings offers bundled / specific version / custom executable |
| **Logs on disk + diagnostic report** | Logs go to `%APPDATA%/AFuturestar/SFS-Pack-Tool/logs/`; closing the app writes a shareable `_report.md` |
| **Robust UnityYAML parsing** | Replaces the single-line regex: reordered fields, block style, quoted guids and missing spaces are now handled (the old regex failed silently — zero replacements, no warning) |
| **Incremental re-export** | Pack fingerprint + Toolkit fingerprint + parts still present means the export can be skipped |
| **CLI and GUI parity** | `--overwrite` actually works, `-i` accepts multiple files, plus `--preview` / `--backups` / `--restore` / `--probe` |

#### New Settings page (menu bar "Settings")

Space-consuming, rarely-used options moved in: **AssetRipper version**, log folder and
retention, the incremental-export toggle and the Toolkit probe. **Changes apply only
after clicking Apply**; Cancel or closing the window saves nothing (a wrong version here
makes exports fail outright, so there has to be a way back).

#### Bugs found during review and fixed

1. **PE row widths used the wrong rule (most severe)**: `sfs_assembly_rename._row_size`
   sized coded (composite) indexes as if they were plain table indexes. `CustomAttribute`'s
   `HasCustomAttribute` is a 5-bit coded index (threshold 2048) and needs 4 bytes in real
   large assemblies, but was counted as 2 — the table offset drifted and the assembly
   identity read back empty. Measured: `Assembly-CSharp.dll` (1.2 MB) yielded no name,
   while small dlls (ilspycmd, method count below the threshold) passed by luck. Rewritten
   per ECMA-335; `Assembly-CSharp` / `UnityEngine` / `ilspycmd` now all read correctly.
2. **An empty name was treated as a legal filename**: following the bug above, the plugin
   would land as `Assets/Plugins/.dll`, which Unity cannot resolve. `read_assembly_name`
   now raises on an empty name and `_unique_assembly_for_mod` falls back to the original.
3. **Incremental export never took effect**: `record_export()` wants a **list of part
   names**, but the caller passed a count plus a nonexistent `installed` keyword — a
   TypeError swallowed by the surrounding except, so the index was never written and every
   run looked like a first export. Now collected from the exported project.
4. **Selecting an AssetRipper version always failed**: the GUI always passed
   `no_download=True` (designed for the bundled build), while the version branch skips the
   bundled copy — so any change of version made the export fail. Downloads are now allowed
   only when the user explicitly picks a version/path, and picking the same version as the
   bundled build reuses it instead of demanding a download.
5. **The diagnostic report was never generated**: `DiagnosticLog.close()` was never called.
   Closing the app now finalises it with the selected pack and Toolkit.

#### Other

- The Settings window is centred on the main window (it used to sit in the screen corner
  with its description clipped).

#### Verification

| Test | Result |
| --- | --- |
| `test_core_smoke.py` | 192 checks, ALL PASS |
| `test_custom_scripts.py` / `test_dedupe_cs0101.py` | 39 / 20 pass |
| `test_unity_yaml.py` | 43 pass |
| `test_multi_assembly.py` / `test_two_mods_coexist.py` | 24 / 19 pass |
| `test_toolbox.py` / `test_cli.py` / `test_round2.py` | 58 / 27 / 30 pass |
| GUI smoke (settings draft semantics / incremental loop / diagnostic report) | 15 pass |

**467** dedicated checks plus the existing regression, all green. End-to-end coexistence
verified: two mods with custom dlls land as `CodeAsm_0c44.dll` and `CodeAsm_5dfe.dll` in the
same Toolkit and both resolve.

---

## v2.3.4 — 2026-10-17

### 中文

本版修复了一个**会静默损坏 Toolkit 的缺陷**，优先级高于其余所有条目，请优先更新。

#### 严重：原版脚本可能被误删（2026-09-18 事故的根因）

- **现象**：Toolkit 版本与模组作者不一致时，导出后**原版（游戏自带）脚本**会被当成
  模组自定义脚本，其占位 stub 被删除，导致原版脚本在 Unity 里全部变成 Missing Script。
- **根因**：真实 `.pack` 里 MonoScript 的 `m_AssemblyName` 是 `Assembly-CSharp.dll`
  （**带 `.dll` 后缀**），而判定原版程序集用的名单里是不带后缀的纯名，直接比较必然失配，
  于是**每一个原版类都被判成"自定义类"**。该缺陷自 **v2.3.2 引入**，v2.3.2 / v2.3.3
  均受影响。
- **修复**：比较前先归一化（剥离 `.dll` / `.exe` 后缀，忽略大小写）。实测三个真实模组
  自定义类数由 53 → 2、39 → 12、40 → 10，不再虚高。
- **受影响用户**：如果你在 v2.3.2 / v2.3.3 下导出过，且 Toolkit 版本与模组作者不同，
  请用本版重新导出一次以修复已丢失的原版脚本。

#### 重要：多模组同名程序集冲突会静默覆盖

- **现象**：先后导入两个**都带自定义脚本**的模组，第二个导入后第一个模组的部件脚本
  全部悬空（Unity 报 missing script），日志里看不到任何错误，只有一行
  "已替换 N 个同名残留"。
- **原因**：程序集文件名天生不唯一（`Assets/Plugins/CodeAssembly.dll`，且不能改名——
  MonoScript 的 `m_AssemblyName` 就是它），而"覆盖旧残留"的判定条件对 dll 恰好全部成立。
- **修复**：并入 Toolkit 前预检。检测到**内容不同**的同名程序集即**拒绝并入**，日志逐条
  说明、弹窗点名是哪两个模组，并解释为什么不能改名、该怎么处理。模组名从引用该程序集的
  部件反查，查不到就显示 `?`，**不编造**。
- **不影响正常导入**：字节相同视为同一模组重复导入（正常放行并刷新 GUID）；两份 dll
  文件名不同时可正常共存，不受影响。

#### 修复：源码类型撞名导致 CS0101

- 之前只会拦"同名 dll"，但 CS0101 实际发生在 **`.cs` × `.cs`**（同属 Assembly-CSharp
  编译单元）时。现在并入前会检查本次的源码与 Toolkit 已有脚本是否撞同名**顶层**类型，
  撞了就拒绝并入并弹窗点名类型与两个文件。
- 说明：两个 **dll** 里的同名类型**不会**报 CS0101（预编译程序集各自独立），因此按 dll
  类型名拦截会误伤，已明确不这样做。

#### 改进：自定义类判定退化时不再静默

- 判定退化（无法可靠区分自定义类与原版类）时，现在会**弹窗告知**并说明原因，不再只埋在
  日志里。同时区分"读不出来"与"确实没有自定义类"两种情况，后者不再被误标为退化。

#### 改进：未安装 ILSpy 时给出可操作提示

- 缺少 `ilspycmd` 时明确说明"不影响导入与出包，只是看不到源码"，并给出安装命令
  （`dotnet tool install -g ilspycmd`）与 dnSpy 备选方案。

#### 其他

- **进度条 + 全局忙碌锁 + 缓存清理**：长任务期间禁用所有操作按钮，避免并发操作。
- **导出工程去重**：移除 `Foo.prefab` 与 `Foo_0.prefab` 这类同物异名副本。
- **单平台解码**：默认只解一个平台，从根上解决部件 4 倍重复。
- **并入后自动生成 PackData 资产**并统一 AssetBundle 标签，在 Unity 里选资产 + 标签即可出包。
- **重复的原版资源（燃料等）自动重定向**到 Toolkit 原件，不再产生副本。
- **英文界面**：按钮文案缩写适配、导出过程中切换语言不再报错、日志短语表扩充。
- **并入被拒时不再生成 PackData**：没并进去却盖一个出包入口等于骗用户。

#### 维护

- 注释精简（保留全部关键事实，删除会漂移的行号引用）。
- 移除死代码：`PLATFORM_LABELS`、`safe_remove()`、`dll_assembly_refs()` 及两个只增不读的
  计数器。`VERSION` 与 `collect_monoscript_pathids()` 保留并标注原因。
- 性能：`detect_source_type_conflicts()` 原将包内 `.cs` 扫描三遍，改为一遍。
- README：语言切换由纯文本改为可点击链接；修复英文版两条从未被引用的死链接；EXE 文件名
  由不存在的 `..._prev.exe` 更正为真实产物名。

### English

This release fixes a defect that **silently damaged Toolkits**. It outranks everything
else below — please update for this first.

#### Critical: stock scripts could be deleted (root cause of the 2026-09-18 incident)

- **Symptom**: when the Toolkit version differs from the mod author's, exported
  **stock (game-provided) scripts** were treated as mod custom scripts. Their AssetRipper
  placeholder stubs got deleted, so every stock script showed up as Missing Script in Unity.
- **Cause**: in real `.pack` files, MonoScript's `m_AssemblyName` is `Assembly-CSharp.dll`
  (**with the `.dll` suffix**), while the stock-assembly list holds the bare name. The raw
  comparison therefore never matched and **every stock class was classified as custom**.
  This defect was introduced in **v2.3.2** and affects v2.3.2 and v2.3.3.
- **Fix**: normalise before comparing (strip `.dll` / `.exe`, ignore case). Measured on three
  real mods, the custom-class count drops from 53 → 2, 39 → 12 and 40 → 10.
- **If you are affected**: if you exported under v2.3.2 / v2.3.3 with a Toolkit version
  different from the mod author's, re-export with this release to restore the stock scripts
  that were lost.

#### Important: same-named assemblies across mods were overwritten silently

- **Symptom**: importing a second mod that also carries custom scripts left the first mod's
  part scripts dangling (Unity reports missing script) with **no error in the log** — only
  a line saying "Replaced N same-named leftovers".
- **Why**: assembly filenames are inherently non-unique (`Assets/Plugins/CodeAssembly.dll`,
  and it cannot be renamed — MonoScript's `m_AssemblyName` *is* that filename), while the
  "replace a stale leftover" test happens to be satisfied by a dll in every respect.
- **Fix**: pre-check before merging into the Toolkit. A same-named assembly with
  **different content** now **refuses the whole merge**, logs one line per clash, and pops up
  a dialog naming both mods and explaining why renaming is not an option. Mod names are
  resolved by finding the prefab that references the assembly; when that fails it shows `?`
  rather than inventing a name.
- **Normal imports are unaffected**: identical bytes means the same mod re-imported (allowed,
  and the GUID gets refreshed); two dlls with **different names** coexist normally.

#### Fixed: duplicate type names in sources caused CS0101

- Only same-named *dlls* were being blocked, but CS0101 actually happens for
  **`.cs` × `.cs`** (same Assembly-CSharp compilation unit). The merge now checks whether the
  incoming sources collide with scripts already in the Toolkit on the same **top-level** type
  name, and refuses the merge while naming the type and both files.
- Note: duplicate type names across two **dlls** do **not** cause CS0101 (precompiled
  assemblies are independent), so blocking on dll type names would produce false positives.
  That is deliberately not done.

#### Improved: unreliable custom-class detection is no longer silent

- When detection degrades (custom classes cannot be told apart from stock ones reliably), the
  tool now **pops up a dialog** with the reason instead of burying it in the log. "Could not
  read it" and "there genuinely are no custom classes" are now distinguished, and the latter is
  no longer mislabelled as degradation.

#### Improved: actionable message when ILSpy is missing

- Without `ilspycmd`, the tool now states plainly that importing and building are unaffected
  and only source viewing is skipped, plus the install command
  (`dotnet tool install -g ilspycmd`) and the dnSpy alternative.

#### Also included

- **Progress bar + global busy lock + cache cleanup**: operation buttons are disabled while a
  long task runs, preventing concurrent operations.
- **Exported-project dedupe**: removes same-asset-different-name copies such as `Foo.prefab`
  alongside `Foo_0.prefab`.
- **Single-platform decode**: only one platform bundle is decoded by default, which removes the
  root cause of parts being duplicated 4×.
- **PackData asset auto-generated** after merge, with unified AssetBundle labels — pick the
  asset plus its label in Unity to build.
- **Duplicated stock resources** (fuels and the like) are redirected to the Toolkit originals
  instead of producing copies.
- **English UI**: abbreviated button labels, no more failure when switching language mid-export,
  and an expanded log-phrase table.
- **A refused merge no longer stamps a PackData asset**: stamping a build entry for a mod that
  was not merged in would be misleading.

#### Maintenance

- Comments trimmed (all load-bearing facts kept, drifting line-number references removed).
- Dead code removed: `PLATFORM_LABELS`, `safe_remove()`, `dll_assembly_refs()` and two
  increment-only counters. `VERSION` and `collect_monoscript_pathids()` were kept, with the
  reason noted inline.
- Performance: `detect_source_type_conflicts()` scanned the package's `.cs` files three times
  and now scans once.
- README: the language switch is now a real link instead of plain text; two dead reference
  links in the English version (never referenced by any sentence) are wired up; the EXE
  filename was corrected from the non-existent `..._prev.exe` to the real artifact name.

---

## v2.3.3 — 2026-09-30

### 中文

#### 剥离工具支持多平台

- 剥离从单选下拉改为 Windows / Android / Mac / iOS 四个勾选框，可任意组合保留。
- 输出文件名按所选平台自动命名（如 `包名-Windows+Android.pack`）。
- 旧设置 `strip_platform` 自动迁移为 `strip_platforms`，老用户配置不受影响。
- 一个平台都不勾时直接拒绝执行。

#### 剥离前先扫描并校验

- 剥离前先报告包内实有平台与各自体积，秒级完成（不加载 UnityPy）。
- **所选平台全都不在包里 → 直接拒绝**，绝不写出游戏加载不了的 `.pack`。
- **部分不在 → 警告并只保留实有平台**。结果保证至少保留一个平台与 CodeAssembly。

#### 提取汉化过滤：不再改动官方翻译 key（防游戏显示 NULL）

- 据游戏反编译源码 `SFS.Translations.TranslationVariable`：`TranslatableName` 字段在
  `plainText=0` 时是**按 key 查 `Loc.fields` 翻译表的标识符**，查不到会显示 NULL。
  原提取器把它当显示文本收进翻译表，汉化写回后游戏查表失败——这正是"汉化后影响游戏
  运行"的来源。
- 新增 `sfs_official_keys.py`，从游戏源码 `SFS_Translation.cs` 的 `A()` 调用提取出
  **703 个官方翻译 key**，提取与写回**双向拦截**。
- 实测：`Six_Wide_Parts` 等官方 key 全部被过滤，`Frontier-V Engine` 等模组自有文本正常。

#### 其他

- UI 精简：删除「原始 mod 工程目录」输入行、「选择工程目录」按钮，以及独立的「修复
  Toolkit 空壳着色器·悬空引用」按钮（三者功能已由一键导出自动完成）。
- 默认窗口分辨率 920×770 → 1080×900。

### English

#### Multi-platform stripping

- The strip tool's single-select dropdown became four checkboxes (Windows / Android / Mac /
  iOS), any combination can be kept.
- Output filenames are derived from the selected platforms (e.g.
  `packname-Windows+Android.pack`).
- The old `strip_platform` setting migrates automatically to `strip_platforms`; existing user
  configuration keeps working.
- Selecting no platform is refused outright.

#### Pre-scan and validation before stripping

- Before stripping, the tool reports which platforms are actually present in the pack and their
  sizes. This is fast because UnityPy is not loaded.
- **If none of the selected platforms are present, the operation is refused** — it will never
  write a `.pack` the game cannot load.
- **If some are present, it warns and keeps only those.** At least one platform plus
  CodeAssembly is always preserved.

#### Localization extraction no longer touches official translation keys

- Per the game's decompiled `SFS.Translations.TranslationVariable`: when `plainText=0`, the
  `TranslatableName` field holds a **lookup key into `Loc.fields`**, not display text; if it
  cannot be resolved the game renders NULL. The extractor treated it as display text and wrote
  it into the translation table, so after translating, the game's lookup failed — the source of
  "translating breaks the game".
- New `sfs_official_keys.py` extracts **703 official translation keys** from the game's
  `SFS_Translation.cs` and blocks them in **both** extraction and write-back.
- Verified: official keys such as `Six_Wide_Parts` are all filtered out while mod-owned text
  such as `Frontier-V Engine` is preserved.

#### Also included

- UI cleanup: removed the "original mod project dir" input, the "select project dir" button, and
  the standalone "repair Toolkit stub shaders · dangling refs" button — all three are now
  handled automatically by the one-click export.
- Default window size 920×770 → 1080×900.

---

## v2.3.2 — 2026-09-18

> 说明：这一版的提交信息较为笼统，以下内容依据仓库内可核实的改动整理。
> Note: the commit messages for this release are terse; the entries below are derived from
> verifiable changes in the repository.

### 中文

#### 工程结构重构（重要）

- 单文件程序拆分为多个模块，便于维护与测试：
  - `sfs_pack_tool_gui.py`（原 `v22-CN.py`）—— GUI 与主流程
  - `sfs_pack_core.py`（**新增**）—— 核心逻辑
  - `sfs_project_exporter.py`（原 `sfs_pack_prefab_export.py`）—— AssetRipper 调用
  - `sfs_toolkit_script_check.py`（原 `sfs_pack_prefab_extract.py`）—— 脚本引用校验
  - `toolkit_stub_cleaner.py`（原 `clean_toolkit_stubs.py`）
- 新增离线回归测试 `test_core_smoke.py`。
- 新增内置使用教程 `tutorial.html`（打进 EXE，可离线查看）。
- 移除已弃用的 `sign.bat` / `build_and_sign.bat`。

#### ⚠️ 本版同时引入了 v2.3.4 才修复的原版类误判缺陷

参见 v2.3.4 的"严重"条目。该缺陷自本版起存在，**v2.3.2 / v2.3.3 用户请升级到 v2.3.4**。

### English

#### Project restructure (significant)

- The single-file program was split into modules for maintainability and testability:
  - `sfs_pack_tool_gui.py` (was `v22-CN.py`) — GUI and main flow
  - `sfs_pack_core.py` (**new**) — core logic
  - `sfs_project_exporter.py` (was `sfs_pack_prefab_export.py`) — AssetRipper invocation
  - `sfs_toolkit_script_check.py` (was `sfs_pack_prefab_extract.py`) — script-reference checks
  - `toolkit_stub_cleaner.py` (was `clean_toolkit_stubs.py`)
- Added the offline regression suite `test_core_smoke.py`.
- Added the bundled usage guide `tutorial.html` (packed into the EXE, works offline).
- Removed the obsolete `sign.bat` / `build_and_sign.bat`.

#### ⚠️ This release also introduced the stock-class misdetection fixed in v2.3.4

See the "Critical" entry under v2.3.4. The defect exists from this release onward —
**v2.3.2 / v2.3.3 users should upgrade to v2.3.4**.

---

## v2.3.1 — 2026-09-13

> 说明：本版提交信息笼统，仅记录可核实项。
> Note: commit messages are terse here; only verifiable items are listed.

### 中文

- 脚本挂空（keep-alive）逻辑调整，修正写入异常。
- README 补充 Termux 安装说明与联系方式。

### English

- Script keep-alive logic adjusted, fixing a write failure.
- README: added Termux installation instructions and contact details.

---

## v2.3 — 2026-09-12

### 中文

- 本项目首个带语义化版本号的公开发行。
- 集成本地化（提取 / 写回汉化）、`.pack` 平台剥离、Prefab 与贴图导出、Unity 工程导出。
- 内置 AssetRipper 1.1.4 Windows x64 运行时，导出无需联网、无需自行配置 AssetRipper。
- 因内置 AssetRipper，整体以 GPL-3.0 分发。

### English

- First public release carrying a semantic version number.
- Combines localization (extract / write translations), `.pack` platform stripping, Prefab and
  texture export, and Unity project export.
- Embeds the AssetRipper 1.1.4 Windows x64 runtime, so exporting needs no network access and no
  manual AssetRipper setup.
- Distributed under GPL-3.0 because AssetRipper is bundled.

---

## 版本对照 / Version map

| 版本 | 日期 | 一句话 / In one line |
| --- | --- | --- |
| v2.3.4 | 2026-10-17 | 修原版脚本误删、同名程序集覆盖、CS0101 源码撞名<br>Fix stock-script deletion, assembly overwrite, CS0101 source clash |
| v2.3.3 | 2026-09-30 | 多平台剥离 + 官方 key 过滤<br>Multi-platform strip + official-key filtering |
| v2.3.2 | 2026-09-18 | 工程模块化重构<br>Modular restructure |
| v2.3.1 | 2026-09-13 | 挂空逻辑修正<br>Keep-alive fixes |
| v2.3 | 2026-09-12 | 首个语义化版本<br>First semantic release |