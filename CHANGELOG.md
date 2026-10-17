# 更新日志 / Changelog

本文档同时提供中文与英文两种表述，两侧内容一一对应 / This document is written in
Chinese and English side by side; both versions carry the same content.

格式沿用 Keep a Changelog，版本号遵循语义化版本 / Format follows Keep a Changelog,
versions follow semantic versioning.

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