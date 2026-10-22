# 更新日志

## 2026-10-22 界面改成任务栏（标签页）式布局

### 三个功能各占一个标签页

之前「还原（导出工程）/ 汉化 / 剥离」三个分区竖着堆在同一个长页面里，窗口
得拉到很高才够用，操作之间也容易看错行。现在改成 `ttk.Notebook` 标签页：

| 标签页 | 内容 |
| --- | --- |
| **① 还原（导入工程）** | Toolkit 路径 + 并入选项 + 一键导出工程 |
| **② 汉化** | 提取待翻译文本 / 写入汉化并生成 Pack |
| **③ 剥离** | 平台多选 + 包信息 + 剥离到所选平台 |

- 「输入文件」区（选 .pack / 选翻译 JSON）留在标签页**外面**，三个标签页共用——
  换标签页不用重新选文件。
- 切换标签页**不打断正在跑的任务**（任务都在后台线程里跑，与界面无关）。
- 标签页标题随语言切换（中文 `① 还原（导入工程）` / 英文 `1. Restore (import)`）。
- 窗口默认尺寸从 `1080x900` 压到 `1080x760`，最小尺寸 `960x800` → `940x620`
  （标签页布局下每块内容各占一屏，不需要那么高的窗口）。

### 版本号文档同步

`tmp/_gen_stats.py`、`待解决问题.md` 里残留的 `v2.3.3` 字样一并更新为 `v2.3.4`
（代码 / spec / bat / tutorial.html 此前已是 2.3.4）。

### 验证

- 核心回归 **192 项 0 失败**（ALL PASS）。
- 新增标签页布局专项 17 项（真实 Tk 主循环）：三个标签页存在且标题互不相同、
  每个页有内容、导出/汉化/剥离按钮确实落在各自页内、三页都能切换、
  **切标签页期间任务未被打断**、切语言后标签页与标题仍在、默认窗口高度已压缩。

---

## 2026-10-17 显示版本升为 v2.3.4

`VERSION` / `VERSION_TITLE` / 窗口标题（中英两处）/ `APP_USER_MODEL_ID` /
模块 docstring / `tutorial.html` 页眉 / `SFS_Pack_Tool.spec`（注释与 `name=`）/
`build.bat` / `build_and_sign.bat` / `sign.bat`（GBK，编码已核对）/
`README.md` / `README_BUILD.md` / `GPL_COMPLIANCE.md` / `CODE_STATS.md`
全部改为 `2.3.4`。

本版内容 = 下方三条（代码清理 + P1-1/P1-2/P2-1 + P0-1）。产物：
`dist/SFS_Pack_Tool_v2.3.4_Embedded_GPL.exe`（Python 3.10 + PyInstaller 6.22.2）。

---

## 2026-10-17 代码清理：注释精简 + 死代码清理 + 一处性能修复

### 注释精简（保持中文，砍掉啰嗦部分）

- `restore_custom_scripts()` 里的事故警告由 13 行压到 4 行，保留全部关键事实
  （`.dll` 后缀误判 → 原版类落进 removable → stub 被删 → 原版脚本全挂）。
- `_is_stock_assembly` / `detect_assembly_conflicts` / `detect_source_type_conflicts` /
  `custom_monoscript_classes_diagnose` 的 docstring 各自缩短约 40%，只留"为什么"不留
  "是什么"（后者代码自明）。
- 去掉注释里会漂移的行号引用（改为按函数/变量名指路）。
- 全部注释本就是中文（纯英文注释只剩 shebang / coding 头 / 代码片段示例，必须保留）。

### 死代码清理（用 AST 全库交叉引用核实，不靠肉眼）

删除：
- `PLATFORM_LABELS`（GUI）—— 多平台改名后遗留的反向字典，无人引用；
- `safe_remove()`（exporter）—— 无调用方；
- `dll_assembly_refs()`（core）—— 只是 `assembly_refs_from_bytes()` 的 3 行封装，
  后者已覆盖同一能力；
- `build_script_guid_map()` 里 `meta_count` / `matched_cs` 两个只累加从不读取的
  计数器（顺带省掉每轮循环里的两次无用自增）。

保留并**标注原因**（删了风险大于收益）：
- `VERSION`——版本号单一信息源，改版本时还要同步 spec / 三个 bat / APP_USER_MODEL_ID /
  tutorial.html，删了更容易漏改；补了注释列全同步点。
- `collect_monoscript_pathids()`——当前无调用方，但它是「AssetRipper 一个 stub 都不
  生成时如何对齐」那条设计的原理依据，docstring 里注明别当死代码删。

### 性能：`detect_source_type_conflicts()` 少扫两遍

包内 `.cs` 原被扫描 3 次（`incoming` + `package` 两次），每次都要读文件 + 跑正则。
改成只扫一次、结果复用于两侧；顺带把去重用的 `any(...)` 线性查找换成 `set`。
dll 路线（包里无 `.cs`）仍然零开销——那是最常见的路径。

### 一处日志级别修正

`install_src_conflict_scan_fail` 补上 `[!]` 标记：这道预检失败意味着"可能有 CS0101
风险却没拦住"，不该和普通信息同色。文案改为明确要求用户去 Unity 确认能编译过。

### 验证

`test_core_smoke.py` 192 项、`test_custom_scripts.py` 39 项、`test_dedupe_cs0101.py`
20 项全过；i18n 中英各 193 键完全对称。真实链路回归（真 AssetRipper 导出 → 对齐 →
合并 → 并入）通过：撞名仍被拦截并弹窗点名，基线对照 unresolved 17→17 未变差。

---

## 2026-10-17 修 P1-1 / P1-2 / P2-1（含一个会真实损坏用户资产的隐藏 bug）

### ⚠️ 先说最重要的：原版类被误判成自定义类（默认开启的事故链）

用三个真实模组实测时发现，比 P1-1/P1-2/P2-1 都严重：

- 真实 .pack 里 UnityPy 读出的 `m_AssemblyName` 是 **`Assembly-CSharp.dll`（带
  `.dll` 后缀）**，而 `STOCK_ASSEMBLY_NAMES` 存的是**不带后缀**的纯名。原代码
  `asm.lower() not in STOCK_ASSEMBLY_NAMES` 拿原串直接比 → **每个原版类都被判成
  "自定义类"**（实测三个模组共 88 个原版 MonoScript 全是这个形态）。
- 于是「权威路径」（m_AssemblyName）一直在干和「退化路径」同样的事：Artemis 被数成
  53 个自定义类（实际 2 个）、moreparts 39 个（实际 12 个）、Power System 40 个
  （实际 10 个）。
- 事故链因此**不需要任何退化触发条件，默认开启**：
  `restore_custom_scripts()` 里 `removable = own ∩ unresolved_classes ∩ (不在 Toolkit)`，
  某个原版类只要因 Toolkit 版本不匹配而查不到源码，就落进 `removable` →
  AssetRipper stub 被删 → prefab 指向的 GUID 消失 → **原版脚本全挂**。
  这正是 2026-09-18 那次事故的机制，当时归咎于"判定退化"，实际权威路径一样中招。
- 同源错误还有第二处（`align_scripts_to_toolkit` 里把自定义 GUID 指到 dll），当时恰好
  因 Plugins 里找不到同名 dll 而没发作，属潜伏隐患，一并修了。

修法：新增 `_is_stock_assembly()` 做归一化（剥 `.dll`/`.exe` 后缀 + 大小写不敏感），
两处比较统一走它。

### P1-1　自定义类判定退化要看得见（可观测性）

- 新增 `custom_monoscript_classes_diagnose()`：在返回类集合之外**带上退化原因**，
  并区分三种情况：① MonoScript 都没读出来；② 类名读到了但没有 `m_AssemblyName`；
  ③ 确实没有自定义类（**这不是退化**）。
- `scan_pack()` 增 `custom_reliable` / `custom_reason`；权威判定出"确认无自定义类"时
  `custom_source` 标为 `assembly_name(确认无自定义类)`，不再冒充退化口径（否则 route
  会被误导成 manual，custom_classes 还会平白多出一堆原版类）。
- GUI：扫描判定退化时**弹窗**告知（不再只埋日志），并说清为什么这份口径不可信、
  常见原因是 Toolkit 版本对不上。可信时不打扰用户。

### P1-2　CS0101：拦在真正会触发的地方（原方案前提有误，未采纳）

- 原方案是"扫 dll 类型名、与既有 dll 重名就拒绝"，**没有采纳**：预编译 dll 由 Unity
  只做引用不编译，两个程序集同名类型**不构成 CS0101**；而且按短名拦会直接误伤真实
  模组——实测 Artemis 与 moreparts 的 dll 里都有短名 `BalloonModule`（命名空间不同）。
- 真正的触发面是 **`.cs` × `.cs`**（都会被编译进 Assembly-CSharp）：dll 没被认成插件时
  `restore_custom_scripts()` 会退回"反编译源码接回"，把 .cs 写进 `Assets/Scripts/ModCode/`，
  两个都走这条路的模组就会在同一份 Toolkit 里各留一份同名类型的 .cs，此前**从未被检查**。
- 新增 `detect_source_type_conflicts()`：并入前预检，本次要装的 .cs 与 Toolkit 已有
  的 .cs（以及包内自撞）撞同名**顶层**类型就拒绝并入，弹窗点名类型与两个文件。判据与
  `find_duplicate_types` 对齐（全限定名 + 非 partial + 只算顶层，嵌套同名不算）。
  默认的 dll 路线包里没有 .cs，这道预检零开销。
- 这道预检**故意 fail-open**（与程序集预检相反）：预检自身出错时放行 + 打日志。因为
  两者后果不对称——程序集那条漏了会静默顶掉别人已装好的模组，而源码这条漏了最坏是
  Unity 打开当场报 CS0101（用户自己就能看见、能修）。

### P2-1　缺 ilspycmd 不再静默跳过

- `decompile_assembly()` 的日志改成说清"不影响导入与出包、只是看不到源码"，并带上
  安装命令（新增 `ilspy_hint()`）。
- GUI 在扫描阶段发现"包带 dll 但机器上没有 ilspycmd"时弹一次说明窗（不阻断导出）。
- 「反编译 → 编辑 → 重新编译 → 自动装回」这个大工作量项**有意未做**。

### 测试

`test_core_smoke.py` 130 → **192 项全过**（新增 4f 源码撞名、4g 判定退化可见、
4h ilspy 提示、4i `.dll` 后缀回归 + 4d/4e P0-1）。`test_custom_scripts.py` 39、
`test_dedupe_cs0101.py` 20 仍全过。`PyInstaller SFS_Pack_Tool.spec` 打包通过。

真实模组复验（Artemis.Program / moreparts / Power System）：三个包的自定义类
53→2、39→12、40→10，P0-1 两两仍被拦，dll 路线的包不会被源码撞名预检误伤。

---

## 2026-10-17 修 P0-1：多模组 dll 同名冲突（后装的模组静默顶掉先装的）

### 现象

Toolkit 里先后导入两个**都带自定义脚本**的模组，第二个导入后第一个模组的部件
脚本引用全部悬空（Unity 报 missing script），日志里**看不到任何错误**，只有一行
`[安装] 已替换 2 个 GUID 过期的同名残留`。用户观感是"我只是导入了第二个模组，
怎么第一个模组坏了"。

### 根因（三层叠加）

1. **文件名不唯一**：方案 B 把每个模组的 dll 都落成 `Assets/Plugins/CodeAssembly.dll`。
   这个文件名**不能改**——MonoScript 的 `m_AssemblyName` 就是它。
2. **安装层例外太宽**：`install_into_toolkit` 的「例外 1：GUID 过期占位」是为
   *贴图/材质*设计的，判据是"同名 + guid 不同 + 新 guid 在包内被引用"，dll 恰好
   **完全满足**这三个条件 → 后装的 dll 静默盖掉先装的。
3. 没有"多程序集共存"概念：整个流程默认一个 Toolkit 里只有一份 mod 程序集。

### 修复（采用方案 A：检测到就拒绝合并并弹窗点名）

- 新增 `sfs_pack_core.detect_assembly_conflicts()`：并入前预检——Toolkit 的
  `Assets` 下若已有**内容字节不同**的同名 `.dll`，返回冲突清单（dll 名、相对
  路径、双方 GUID、**双方模组名**）。模组名按 `Assets/Resources/Parts/<模组名>`
  下的部件反查哪个 prefab 引用了该程序集的 GUID，反查不到就显示 `?`（宁可说
  不知道，也不编一个模组名）。
- `install_into_toolkit()` 在**一个文件都还没写之前**先过这道预检；命中就拒绝
  整个并入（不是只跳过 dll），逐条打日志 + 弹窗点名两个模组，并说明为什么不能
  改名（`m_AssemblyName`）与三条处理办法（含手工合并 dll 时必须改类名，否则
  Unity 报 CS0101）。合并包仍留在原处供人工处理。
- **只在内容不同时拦**：dll 字节相同 = 同一个模组重复导入（每次导出都会重新生成
  .meta GUID），必须放行并靠覆盖刷新 GUID，否则重导同一个模组反而会让自己挂空。
  贴图/材质同名不同内容是正常变体，不在拦的范围内（预检只看 `.dll`）。
- 读取失败一律**不判冲突**（宁可漏拦也不误拦，日志里另有兜底）。
- 并入被拒时返回 `False`，导出流程据此**跳过 PackData 盖章**——没并进去还盖个
  出包入口等于骗用户。

### 实测（三个真实模组，两两组合）

用 `Artemis.Program.pack` / `moreparts.pack` /
`Power System and Thermal Management System Test Package.pack` 的真实 CodeAssembly
跑完整并入流程（`MZ_` 桩数据无法覆盖的真实字节）：

- 三组组合全部：并入被拒、先装模组的 dll 字节与 GUID 均未变、先装模组部件引用
  仍命中自己的 dll、后装模组的部件也没被写进去、弹窗与日志都点名两个模组及双方
  GUID 前 8 位。
- 对照组（把预检关掉模拟修复前）：dll 被静默顶掉，日志只剩
  `install_replaced_stale` 一行 —— 确认这道预检就是关键闸门。
- 同一模组重复导入：放行，dll 字节不变、meta GUID 刷新为新 GUID。

### 顺带发现（仅记录，未改）

三个模组的程序集**内部名互不相同**（`InterplanetaryModule.dll` /
`MorePartsMod.dll` / `AssetsofIce.dll`），只是都被方案 B 统一改名成了
`CodeAssembly.dll`。也就是说它们本可以靠不同文件名共存——待解决问题.md 的
方案 B（自动改名共存）风险面比当初评估的小。但改名要同步改写导出工程里
MonoScript 的 `m_AssemblyName`，属高风险改动，本次不动，留待单独评估。

### 测试

- `test_core_smoke.py` 新增 4d（同名程序集冲突：拒绝并入 + 点名两个模组 + dll
  字节/GUID 未变 + 整个并入都没写 + 英文界面同样点名 + 核心预检返回结构）与
  4e（反向护栏：同一模组重复导入必须放行并刷新 GUID、贴图同名不同内容不误伤）。
- 验证：`test_core_smoke.py` 150 项全过（此前 130），
  `test_custom_scripts.py` 39 通过 0 失败，`test_dedupe_cs0101.py` 20 通过 0 失败；
  `PyInstaller SFS_Pack_Tool.spec` 打包通过。

## 2026-09-27 多平台剥离 / 提取文本过滤 / UI 精简（显示版本 v2.3.3）

### 1. 剥离精简工具支持多平台

- `strip_pack()` 改为接收**平台列表**（同时兼容旧的单平台字符串参数），UI 的
  单选下拉换成 Windows / Android / Mac / iOS 四个勾选框，可任意组合保留。
- 输出文件名默认按勾选平台生成（如 `包名-Windows+Android.pack`）；设置键
  `strip_platforms`（列表）取代 `strip_platform`，旧设置自动迁移。
- 保留平台一个不勾时弹窗拒绝执行。

### 2. 剥离前先扫描并校验包信息

- 剥离前先扫描包内实有平台并逐个输出体积（不加载 UnityPy，秒级完成）。
- **所选平台全不在包里 → 直接拒绝**，绝不写出一个不含任何平台的
  （游戏加载不了的）.pack；**部分不在 → 警告并只保留实有平台**。
- 结果保证至少一个平台 + CodeAssembly。

### 3. UI：Modding Toolkit 工程路径增加浏览按钮

「Unity Prefab / 贴图 / 工程导出」区的 Toolkit 路径输入框旁新增
「选择 Toolkit」浏览按钮，弹目录选择框并自动上溯校正到工程根。

### 4. UI 精简：删除冗余入口

- 删除「原始 mod 工程目录(可选 用于按名修复悬空引用)」输入行；
- 删除「选择工程目录 (Toolkit + 原始mod)」合并选择按钮；
- 删除独立的「修复 Toolkit 空壳着色器·悬空引用」按钮（同日追加）。
  三者功能已由一键导出工程自动完成（`repair_toolkit()` 保留，导出时自动清理
  空壳着色器与悬空引用）。`package_dir` 仍从设置文件读取，
  老用户的既有配置继续对悬空引用自愈生效。

### 5. 默认窗口分辨率调大

`920x770 → 1080x900`，`minsize 840x680 → 960x800`，启动后日志栏默认完整可见。

### 6. 提取文本过滤：不再提取/汉化官方翻译 key（防游戏显示 NULL）

- 根因（据游戏反编译源码 `SFS.Translations.TranslationVariable`）：
  `TranslatableName` 字段在 `plainText=0` 时是**按 key 查 `Loc.fields`
  翻译表的标识符**（如 `Six_Wide_Parts`→"6 Wide"、`Frontier_Engine_Name`），
  查不到会显示 NULL。此前提取器把它当显示文本收进翻译表，汉化写回后
  游戏查表失败——这就是"这些文本被汉化后影响游戏运行"的来源。
- 修复①（结构过滤）：`TranslatableName` 且 `plainText=0`（或缺省，按 C#
  默认 false 处理）的值不再提取；`plainText=1` 的直显文本照常提取。
- 修复②（官方 key 全集过滤）：新增 `sfs_official_keys.py`，内含从游戏源码
  `SFS_Translation.cs` 的 `A()` 调用提取的 **703 个官方翻译 key**；提取与
  写回**双向拦截**——任何字段里撞上官方 key 的串不进提取表，老版本提取的
  JSON 里已混入的官方 key 也不会被写回 pack。
- 实测 `MSEP_1.0.5 (1).pack`：`Six_Wide_Parts` / `Ten_Wide_Parts` /
  `Eight_Wide_Parts` / `Frontier_Engine_*` 全部被过滤，
  `Frontier-V Engine` 等 mod 自有文本正常保留。

### 7. 测试

- `test_core_smoke.py` 新增 2c 多平台剥离断言（保留集合 / 全缺失拒绝 /
  部分缺失警告）与 2d 提取过滤断言（plainText 结构过滤 / 官方 key 拦截 /
  写回防护）。
- 验证：`test_core_smoke.py` 98 项全过，`test_custom_scripts.py` 39 通过
  0 失败，`test_dedupe_cs0101.py` 20 通过 0 失败；GUI 中英文重建冒烟通过。

### 8. 显示版本升为 v2.3.3

`VERSION` / `VERSION_TITLE` / 窗口标题（中英两处）/ `APP_USER_MODEL_ID` /
docstring / `tutorial.html` 页眉 / `SFS_Pack_Tool.spec` 注释与 `name=` /
`build.bat` / `sign.bat`（GBK） / `build_and_sign.bat`（UTF-8） / `README.md` /
`README_BUILD.md` / `GPL_COMPLIANCE.md` 全部改为 `2.3.3`。产物：
`dist/SFS_Pack_Tool_v2.3.3_Embedded_GPL.exe`（Python 3.10.9 + PyInstaller 6.22.2）。

### 9. 剥离校验补丁：空值平台按"不存在"处理（同日追加）

- 用户报"模组没有安卓支持但剥离里有安卓选项"的隐患。核对结论：v2.3.3 的剥离
  校验已覆盖主场景——所选平台**全不在包里 → 拒绝**（绝不产出零平台包），
  **部分不在 → 警告**并只保留实有平台。
- 但发现一个真实漏网边界：**平台键存在而值为空字符串**时，`base64.b64decode("")`
  返回 `b""` 而非报错，空值平台会被误判为"存在"并被保留 → 剥出的包带一个
  游戏加载不了的空平台块（实测有包的字段确实存在但值为空，如 test.pack 的
  `CodeAssembly`）。已修：`decode_build_payload()` 把解码结果为空也判为不存在，
  `analyze_pack` / `strip_pack` 同时受益。
- 回归新增 3 项断言（空值平台只选时拒绝 / 混选时不保留 / 包信息不计为存在），
  `test_core_smoke.py` 101 项全过。

### 10. UI 易用性优化（2026-09-30 追加）

- 输入文件区新增**翻译 JSON 状态行**：选没选翻译文件一眼可见（此前只在日志里）。
- 剥离输出默认名**跟随平台勾选自动刷新**（如 `包名-Windows+Android.pack`）；
  手动选过输出路径后不再自动覆盖。
- **记住窗口大小与位置**：关窗时保存，下次启动原样还原（未记录时用默认 1080x900）。
- 日志栏右上新增**「清空日志」**按钮。

### 11. 燃料/资源副本重定向：修 Flow.resourceType 指向模组私有燃料（2026-09-30）

- **问题**（RDEP3.0.0 实测）：导出后部分部件 Flow 模块的 `resourceType` 引用
  模组私有的 `RDEP3.0.0_Liquid_Fuel` 而非 Toolkit 自带的 `Liquid_Fuel`。
  SFS 运行时燃料匹配是**引用相等**，引用副本的部件与引用原版的油箱**燃料互不流通**。
- **根因**：AssetRipper 导出的副本与 Toolkit 原版只差 3 处无语义噪声——
  `m_EditorClassIdentifier`（纯编辑器元数据）、`plainText: 0`（C# 默认值=缺省）、
  `m_Name`（模组作者加前缀时必改）——等价判定把它们当成"mod 改过的版本"保留。
- **修复**（`sfs_pack_core.py`）：
  - `_norm_asset_text` 抹平 `m_EditorClassIdentifier` 与 `plainText: 0` 噪声；
  - 新增 `_norm_asset_key` 规范化名匹配（剥 `_0/_1` 序号后缀、模组名前缀）；
  - 规范化名命中时用 `ignore_name` 等价判定（忽略 m_Name），其余照旧严格。
  - 修复后：前缀副本/序号副本被自动重定向到 Toolkit 原版并删除副本，引用改指原版；
    真改过的资产仍保留（负面对照测试覆盖）。
- 回归新增 2e 共 8 项断言，全套 108 项 0 失败（2d/2h 既有去重行为不变）。

### 12. PackData 自动生成 + PickCategory 副本重定向（2026-10-01 追加）

- **Variants tag 同理修复**：`Variants.PickTag.tag` 指向 `PickCategory`
  ScriptableObject，与燃料同构。等价噪声掩码追加 `TranslatableGroup:`（AssetRipper
  导出常丢该字段，实测 RDEP `RDEP3.0.0_Engines` 缺 `TranslatableGroup: Pick List
  Names`）。实测全工程 27 个模组侧 PickCategory：9 个原版分类副本（RDEP3.0.0_Engines、
  RSS Engines_Basic/Other/6 wide、lasers Engines_0/1/2 等）会被自动重定向，
  14 个模组真自建分类（Lasers、New Starship、Side Boosters 等）不受影响。
- **PackData 自动生成**（`sfs_pack_core.generate_pack_data`）：一键导出并入 Toolkit
  后自动完成 ModBuilder 出包前的全部准备——
  1. 从原 .pack 用 UnityPy 读出模组元数据（显示名/版本/描述/作者，作者填过的那套）；
  2. 生成 `Assets/ModBuilder/PackData/<模组名>.asset`（m_Script 指向该 Toolkit 自己
     的 PackData.cs；图标有则连 PNG 一起导出并挂引用）；
  3. 给 `Resources/Parts/<模组名>` 与 `Assets/<模组名>` 全部资产统一标签
     `<模组名>`（Importer 块内 Unity 真正读取的位置，guid 保留）；
  4. 原包带 CodeAssembly 时顺手导出 dll 供构建弹窗选择。
  全部改动先备份到 `_PackToolBackup/`。用户在 Unity 里 SFS→打包模组包，选资产+
  标签即可出包，无需再手填任何元数据。
- 回归新增 2f 共 10 项断言（元数据写入/脚本 guid 指向/标签位置/文件夹 meta 不标注/
  幂等），全套 119 项 0 失败。

### 13. 导出工程去重：移除 X 与 X_0 重复资产（2026-10-01 追加）

- **问题**：导出的 Unity 工程里 `Foo.prefab` + `Foo_0.prefab`、`Fuel.asset` +
  `Fuel_0.asset` 成对出现（内容一致 GUID 不同），打进游戏部件/资源目录翻倍。
- **根因**：① 导出暂存目录 `SFS_Pack_Stage/<模组>_export` 复用，二次导出时
  AssetRipper 对同名文件自动加 `_0` 序号；② mod 打包时本身就把同一资产打了多份。
- **修复**（两层）：
  1. `start_export` 导出前先清空暂存目录（`shutil.rmtree`）；
  2. 新增 `dedupe_export_assets()`：工程内按（目录, 规范化名, 扩展名）分组，
     组内与首选成员（无序号者）**等价**（忽略 m_Name、guid 打码）的副本 → 引用
     改指首选、删除副本（含 .meta）；内容确有差异的真变体保留。删除/改写前
     全部备份到导出工程 `_DEDUPE_BACKUP/`。
- 回归新增 2g 共 7 项断言（副本删除/引用改指/真变体保留/备份/幂等），
  全套 126 项 0 失败。

### 14. 单平台解码：根治 4 平台部件重复（2026-10-01 追加）

- **问题**（Artemis Program 实测）：导出工程 496 个 prefab，实际只有 ~125 个部件
  ——`X / X_0 / X_1 / X_2 / X_3` 正好是 4 个平台包各导一份，二次导出再叠 `X_0_0` 系。
  去重步骤抓不住它们：跨平台序列化差异让等价判定失败。
- **根治**（`sfs_project_exporter.decode_pack_resources`）：默认 **single 模式只解码
  一个平台**的 bundle（WindowsBuild 优先，缺失按 Mac/Android/iOS 顺延）——四个平台
  包里是同一批资产的各平台序列化版本，Toolkit 用 Windows 版本即可。导出体积/耗时
  同步降为 1/4。`--platforms all`（CLI）/ `platforms="all"`（API）保留旧行为。
- 暂存目录复用清理 + 工程内去重（第 13 节）继续作为兜底。
- 回归新增 2h 共 3 项断言（单平台解码/全平台回退/首选缺失顺延），
  全套 130 项 0 失败（ALL PASS）。

### 15. 界面双语修复（2026-10-02 追加）

- **英文按钮缩写**（修复裁剪）：`Export Unity project` → `Quick Export`、
  `Strip to selected platforms` → `Strip Selected`、`Select translation JSON` →
  `Select translation`、两处 `Choose location` → `Browse...`。
- **导出中可切换语言**：日志写入对控件销毁做了容错（切语言会重建全部控件，
  旧日志控件销毁时日志暂存 `self.logs`、重建后统一重画），导出运行中切换语言
  不再报错/丢日志，导出本身不受影响。
- **英文日志补全**：`_zh2en` 短语表新增 ~60 条（PackData 生成/去重/单平台解码/
  导出器解码/AssetRipper 错误/反编译等），并用模拟脚本对核心库+导出器全部
  304 个中文串做了覆盖验证——新功能日志 0 残留，剩余仅为 MERGE_README.md /
  UNRESOLVED_SCRIPTS.md 等**文件内容**（不进日志）。

### 16. 进度条 + 全局忙碌锁 + 清理缓存（2026-10-02 追加）

- **进度条**（日志栏正上方，`ttk.Progressbar` + 右侧状态文字）：
  - 一键导出按 7 个阶段走**确定进度**：扫描包信息 → AssetRipper 导出 → 脚本免挂
    对齐 → 修复空壳着色器 → 工程去重 → 生成合并包 → 并入 Toolkit + PackData，
    权重按实际耗时分配（AssetRipper 占 40%）；结束时补一次自检并收敛到 100%。
  - 剥离按 4 段：扫描校验 → 剔除多余平台 → 写出 `.pack` → 完成。
  - 包信息按平台逐个推进（解码耗时都在这些 bundle 上），空平台跳过但照样
    打出 `build_absent` 日志（保持原有输出，不丢行）。
  - 其余任务（提取/写入翻译）走未定长动画，完成后自动归零。
- **全局忙碌锁**：任一任务运行期间禁用全部操作按钮（提取/写入/包信息/剥离/导出/
  清理缓存），防止并发操作互相踩坏；进度条与语言切换**始终可用**（导出中仍可切
  中英文）。切语言重建控件后忙碌状态会自动补回。
- **清理缓存**（日志栏右上「清理缓存」按钮，弹窗勾选 + 二次确认）：
  | 项目 | 默认 | 说明 |
  | --- | --- | --- |
  | 导出暂存目录 `%TEMP%/SFS_Pack_Stage` | 勾选 | 下次导出自动重建 |
  | 导出临时残留 `%TEMP%/sfs_prefab_export_*` | 勾选 | 异常中断遗留，占用常最大 |
  | AssetRipper 下载缓存 `.assetripper` | 勾选 | 下次导出重新解压 |
  | 工程去重备份 `_DEDUPE_BACKUP` | 不勾 | ★ 导出目录内 |
  | Toolkit 备份目录 `_PackToolBackup` | 不勾 | ★ 合并/修复前的保险 |
  | 历史 EXE 备份 `dist/_backup` | 不勾 | ★ 保留回滚能力 |
  带 ★ 的是不可恢复数据，默认不勾选；删除在后台线程执行，结束后弹窗报告释放体积。
- **线程安全加固**：新增 `App._ui()` 统一投递回调到主线程，后台线程收尾时若用户
  已关窗不再抛 `RuntimeError: main thread is not in main loop`。
- **坑**：`ttk.Progressbar` 绑定 `variable` 后，写 `widget["value"]` 会被**静默
  忽略**（variable 是唯一数据源），必须写 variable——否则进度条永远停在 0。
- 回归：核心 130 项 0 失败；新增 GUI 专项 27 项（文案键对齐/缓存扫描/删除/幂等/
  进度单调性）+ 真实 Tk 主循环冒烟 13 项全部通过。

## 2026-09-18 脚本改名 / 教程内置 / 显示版本 v2.3.2

### 1. 脚本改名为贴合用途（含全部 import 同步）

| 原名 | 新名 | 用途 |
| --- | --- | --- |
| `v22-CN.py` | `sfs_pack_tool_gui.py` | 主程序界面（Tkinter，中英双语，全流程编排） |
| `sfs_script_keep_alive.py` | `sfs_pack_core.py` | 核心引擎：包扫描 / 脚本免挂三层防护 / 资产归拢 / 合并包 / 自检 |
| `sfs_pack_prefab_export.py` | `sfs_project_exporter.py` | AssetRipper 调用与 Unity 工程导出 |
| `sfs_pack_prefab_extract.py` | `sfs_toolkit_script_check.py` | Toolkit 脚本 GUID 索引 + 部件免挂校验 |
| `clean_toolkit_stubs.py` | `toolkit_stub_cleaner.py` | 清理混入 Toolkit 的 AssetRipper 空壳着色器 |
| `test_keepalive_smoke.py` | `test_core_smoke.py` | 核心引擎冒烟回归 |
| `SFS_Pack_Tool_v22.spec` | `SFS_Pack_Tool.spec` | PyInstaller 打包配置 |

引用同步范围：`sfs_pack_tool_gui.py` 内 10 处 import、`SFS_Pack_Tool.spec` 的
`hiddenimports` 与入口脚本、3 个测试文件的模块加载、`build.bat` / `build_and_sign.bat`、
`README_BUILD.md` / `GPL_COMPLIANCE.md`。图标 `SFS_Pack_Tool_v22.ico` 按约定**未改名**
（spec 里的 `datas` 与 `icon=` 均保持原样）。

### 2. 使用教程内置进 EXE（修掉菜单「教程」在 EXE 里打不开）

`open_tutorial()` 原用 `Path(__file__).resolve().parent / "tutorial.html"`——单文件 EXE 下
`__file__` 指向临时解包目录 `_MEIxxxx`，教程并不在那里，点菜单只会弹「教程缺失」。
现改为走 `resource_path()`（即读 `sys._MEIPASS`），并在 spec 的 `datas` 中加入
`("tutorial.html", ".")`；源码运行时自动退回脚本同目录，两种方式都能打开。
已通过二进制检查确认新 EXE 的 CArchive 目录表内含 `tutorial.html`。

### 3. 显示版本统一为 2.3.2

`VERSION` / `VERSION_TITLE` / 窗口标题（中英两处）/ `APP_USER_MODEL_ID` /
`tutorial.html` 页眉 / spec 注释与产物名 / `build.bat` / `sign.bat` / `build_and_sign.bat`
全部改为 `2.3.2`。

> **版本号说明**：`dist/` 里原本已存在 v2.3.2（「修原版脚本全挂」那一版）。本次按需求
> 沿用 `2.3.2` 作为**显示版本**，旧产物已备份为 `dist/_prev_v2.3.2_<时间戳>.exe`，
> CHANGELOG 既有历史条目**未做重编号**。若日后需要区分两者，建议按产物时间戳辨认。

### 4. 清理历史一次性调试脚本

删除 build_kit 根目录下 9 个一次性诊断脚本及其 `.log`（`_check_guids` / `_check_renderer` /
`_dump_blue_red` / `_find_prefabs` / `_fix_engine` / `_fix_engine2` / `_fix_last` /
`_fix_titan` / `_verify_and_clean`，共 19 个文件），删除前已整体备份到
`tmp/_legacy_debug_backup_<时间戳>/`，可随时取回。

### 5. 新增两份文档

| 文件 | 内容 |
| --- | --- |
| `工具介绍.md` | 对外分发的使用者文档，**中英双语**（顶部锚点切换）。七节：解决什么问题 / 功能总览 / 用法详解 / 保护机制 / 注意事项 / 系统要求 / 菜单与许可 |
| `CODE_STATS.md` | 代码统计：各文件总行·空行·注释·代码行，`sfs_pack_core.py` 的 12 个功能分块与 `sfs_pack_tool_gui.py` 的 8 个功能分组行数，以及 v20→现行版的完整演进对比。由 `tmp/_gen_stats.py` 用 AST 生成，可重跑 |

### 验证与产物

```
test_core_smoke.py      ALL PASS
test_custom_scripts.py  39 通过 0 失败
test_dedupe_cs0101.py   20 通过 0 失败
```

产物 `dist/SFS_Pack_Tool_v2.3.2_Embedded_GPL.exe`：Python 3.10.9 + PyInstaller 6.22.2，
RC=0，耗时 76.7s，58,231,509 字节，PE 头正常；已确认包内含 `tutorial.html`，
启动冒烟 12 秒存活 = **PASS**。构建期仅有 `fmod.dll` 警告
（UnityPy 可选音频依赖，本工具不用），不影响运行。

## 2026-09-18 修「贴图挂空」（v2.3.4）

**症状**：脚本已经不挂了，但零件贴图/材质仍挂空——40 个 prefab 里
`colorTexture` 1002 处、`shapeTexture` 389 处、`m_Sprite` 126 处、`Material` 107 处找不到目标。

**根因**：`install_into_toolkit` 的策略是"已存在就跳过，绝不覆盖"。而**同一个模组重复导入时，
合并包里的资产名与 Toolkit 里的旧版本完全相同，但 GUID 是新导出的**：

| 位置 | 文件名 | GUID |
| --- | --- | --- |
| 导出工程 | `Other/Color_White_0.asset` | `d04d0b37…` |
| 合并包 | `Other/<模组名>_Color_White_0.asset` | `d04d0b37…`（改名时 .meta 一起改，GUID 保留 ✓）|
| Toolkit（旧残留） | `Other/<模组名>_Color_White_0.asset` | `80424ac4…`（上一轮留下的） |

prefab 引用 `d04d0b37`，磁盘上躺着的却是 `80424ac4` → 贴图永久挂空。原来的"悬空引用修复"
判据（比较文件**内部**的悬空数）对贴图不成立：贴图资产自己不悬空，只是**它的 GUID 没被任何人认识**。

**修法**：`install_into_toolkit` 新增一条例外——**GUID 过期占位**：

- 先算出"本次导入真正需要的 GUID 集合"（包内所有 prefab/asset/材质文本里出现的引用）；
- 若 Toolkit 已存在同名文件、其 GUID 与包内这份不同，**且包内这份的 GUID 正在被引用**
  → 说明磁盘那份是历史残留，替换它（原文件照例先备份到 `_PackToolBackup/<时间戳>/`）。

只有 `src_guid ∈ wanted` 才动手，所以 Toolkit 原版资产和"包内 GUID 也没人引用"的同名文件一律不碰。

**验证**：`test_keepalive_smoke.py` 新增 `4c. 并入时替换 GUID 过期的同名残留`，6 项断言全通过。
真实包执行一次：**替换 220 个文件**（110 资产 + 110 .meta），替换前只读预演确认数字一致。

**实测结果**（Toolkit 内该模组 40 个 prefab）：

| 引用种类 | 修复前挂空 | 修复后 |
| --- | --- | --- |
| Script | 7686 | **0** |
| MonoBehaviour（colorTexture/shapeTexture） | 1412 | **0** |
| Material | 107 | **0** |
| Sprite | 126 | **0** |

剩余 18 处 `guid: 0000000000000000f000000000000000` 是 Unity 内置空引用占位，本来就该是空的。

**产物**：`dist/SFS_Pack_Tool_v2.3.4_Embedded_GPL.exe`。

## 2026-09-18 三层防护：彻底修「脚本挂空」（v2.3.3）

**症状**：v2.3.2 之后仍是 40 个 prefab、7686 处脚本引用指向不存在的 GUID。

**真正的根因**（与 2.3.2 判定的那个是两回事）：**AssetRipper 1.1.4 对这个包一个
MonoScript stub 都没生成**（导出 ZIP 里 `.cs` 数量为 0）。而 prefab 里的 `m_Script`
GUID 是 AssetRipper 凭空写的、工程里根本查无此人。于是整条「按 stub 类名重写 GUID」
的链路从源头就是空的——stub 存在与否不可控，机制本身就不可靠。

### 第 1 层：从 .pack 自身做权威映射（根治）

绕过 AssetRipper，直接读 `.pack` 的 AssetBundle：

- prefab：以 `Transform(m_Father==0)` 定位 prefab 根，对 Transform 树做先序遍历，
  键 = `(遍历序, 该 GameObject 上第几个 MonoBehaviour)`；
- ScriptableObject：取 `m_GameObject` 为空的 MonoBehaviour，按 `m_Name` 索引。

导出工程的 YAML 用**完全相同的规则**算出同样的键，两边一 join 就拿到 `guid → 真实类名`，
既不依赖 stub 也不用猜字段。实测：40/40 prefab 配对成功，25 个 GUID 全部还原
（含字段签名会误判的 `PolygonCollider` / `PartVisualizer` / `MathModule` / `MagnetModule`）。

新增：`build_pack_prefab_script_map()`、`resolve_export_script_guids()`、
`_pptr_path_id()` 及一组 YAML 解析工具。

### 第 2 层：字段名签名（仅作对照验证）

Monobehaviour 节点带着完整序列化字段，可与 Toolkit 自带部件的指纹比对。实测高分命中
多数类，但有 4~5 个低置信度/误判（`620d1f50` 被误判成 `ColliderModule`，实际是
`PolygonCollider`），因此**不作为改写依据**，只用于人工核对。

### 第 3 层：合并闸门（止损）

对齐后自检：凡是 `m_Script` 还指向工程里不存在的 GUID → **拒绝生成/合并**，
弹窗列出未接上的类名，并写出 `UNRESOLVED_SCRIPTS.md` 排查清单（含 GUID、类名、
引用次数、出现文件、常见原因）。宁可停下，也不把满屏 `Script is missing` 灌进 Toolkit。

### 顺带修掉

- `verify_toolkit_self()` 现在排除上次合并进来的模组目录，否则会把"自己那份还没修好的
  prefab"算进 Toolkit 自带部件，报出吓人的假告警（实测 7630 → 0）。
- 闸门自检不能复用 `index_asset_guids()`：它为了做合并包会排除 `.cs`/`.dll`，
  而脚本引用指向的恰恰就是它们，会把已修好的全判成挂空。
- `build_merge_package()`：部件"已存在"不再一律跳过——若 Toolkit 那份脚本挂空数更高、
  导出这份更好，则纳入更新。否则重跑一遍根本修不回已经导入的坏部件。
- `collect_unresolved()` 支持 `known_guids`：指向 mod dll 的自定义类引用不该再报未解析。

**验证**：真实包 `Power System and Thermal Management System Test Package.pack`
——m_Script 引用 7748 处，**挂空 0**（此前 7686）；
合并包同样 0 挂空，且 40 个"已存在但挂空"的部件被识别为一并更新。
`test_custom_scripts.py` 39 通过 0 失败，`test_keepalive_smoke.py` ALL PASS。

**产物**：`dist/SFS_Pack_Tool_v2.3.3_Embedded_GPL.exe`（58,226,288 字节，冒烟通过）。
**已导入损坏的 Toolkit 怎么用**：勾选"并入 Toolkit"重跑一次即可自愈——
`install_into_toolkit` 只在"新版本悬空引用更少"时才覆盖，并先备份到 `_PackToolBackup/`。

## 2026-09-18 修「原版脚本全挂」回归（v2.3.2）

**症状**：导入测试包后，mod 自带脚本挂上了，但**原版脚本全部 Missing**（40 个 prefab、
7686 处脚本引用全指向不存在的 GUID）。Toolkit 自带部件不受影响（169/169、188/188 全命中）。

**根因**：自定义类判定依据错了。此前用「包内类名 − Toolkit 类名」判定自定义类，
Toolkit 版本/脚本集不同就会把**原版类也算进来**。实测该包 40 个类里其实只有 **10 个**是
mod 自定义的，另外 30 个是原版类。于是 `restore_custom_scripts` 把 30 个原版类的
AssetRipper stub `.cs` 也当成"与 dll 撞类"删掉了 → prefab 指向的 GUID 随之消失 → 原版脚本全挂。

**修法**：改用 `MonoScript.m_AssemblyName` 作为判定依据（这才是 Unity 自己的解析方式）：

- `Assembly-CSharp` → 游戏原版类（Toolkit 有真源码，stub 保留并由 align 重写到 Toolkit GUID）
- 非 `Assembly-CSharp`（本包为 `AssetsofIce.dll`）→ mod 自定义类，才由 dll 提供、才删 stub

新增 `collect_monoscript_assemblies()` / `custom_monoscript_classes()`；`scan_pack()` 的
`custom_classes` 改为按程序集判定并标注 `custom_source`；`restore_custom_scripts()` 只删
「在 dll 里、且不在 Toolkit 里」的类的 stub，原版类 stub 一律不动。

**验证**：真实包自定义类 40 → **10**（`custom_source=assembly_name`）；新增回归断言
「原版类 stub 保留不动」；`test_custom_scripts.py` 27 通过 0 失败，
`test_keepalive_smoke.py` ALL PASS、`test_dedupe_cs0101.py` 20 通过 0 失败。

**产物**：`dist/SFS_Pack_Tool_v2.3.2_Embedded_GPL.exe`（旧的 v2.3.1 因被占用无法覆盖，
关闭旧程序后可删除 v2.3.1）。

**注意**：已导入损坏的 Toolkit 需要用 v2.3.2 **重新导出一次**才会自愈——
`install_into_toolkit` 检测到「新版本悬空引用更少」会备份后覆盖修复。

## 2026-09-18 导出器日志英文适配 + 重新打包

- `export_project()` 里 `prefab_exporter.log` 由原始 `log` 改为 `self.tlog`：英文模式下
  AssetRipper 导出流程的内部日志也一并翻成英文（此前这段一直是中文）。
- `_zh2en()` 新增标签 `[扫描]`→`[Scan]`、`[整理]`→`[Group]`；新增约 40 条短语，覆盖
  解包前扫描、方案 B 落位、Pack Data `.asset` 保留统计、模组资产归拢，以及导出器原有日志
  （已解码 / 正在启动 AssetRipper / 正在导出 / 已导出 / 工程文件 / 完成 Unity 工程目录 等），
  并补充 `=有`、`=无`、`=是`、`=否` 等短标记。已抽样验证英文输出，且未破坏既有短语的翻译。
- 重新打包 `dist/SFS_Pack_Tool_v2.3.1_Embedded_GPL.exe`：Python 3.10.9 + PyInstaller 6.22.2，
  RC=0，58,216,140 字节，PE 头正常，启动冒烟 6 秒无崩溃。

## 2026-09-17 自定义脚本兼容（方案B）+ Pack Data 音频保留 + 模组资产归拢

### 1. 解包前先扫描包信息（硬性约定落地）
- `sfs_script_keep_alive.py` 新增 `scan_pack(pack, toolkit_root, log)`：解包前先报告
  ① 各平台包是否齐全（MacBuild/IOS_Build 常为 null）② 是否带 `CodeAssembly`（自定义脚本 dll）
  ③ 包内 MonoScript 里哪些是**非 Toolkit 自带**的自定义类 ④ dll 引用的托管程序集
  （`Assembly-CSharp` / `UnityEngine.CoreModule` 等，用于和 Toolkit 版本比对）。
- 配套新增 `dll_assembly_refs()`、`toolkit_script_classes()`。
- `v22-CN.py` 的 `export_project()` 在 AssetRipper 导出**之前**先跑扫描，打印结论与建议路线
  （`B_plugin_dll` / `stock_only` / `manual`）。

### 2. 自定义脚本兼容：方案 B 成为默认（真 dll 当插件，零改 prefab）
- 新增 `install_code_assembly_as_plugin()`：把包内真 dll 落位到 `Assets/Plugins/CodeAssembly.dll`
  （**保留原文件名**，匹配 MonoScript 的 `m_AssemblyName`），并自动补 `.meta` 让 GUID 立即可用。
- `restore_custom_scripts()` 重构：先走方案 B，dll 被识别即返回成功，**不再依赖 ilspycmd**；
  确认走 dll 路线后才删除会撞类的 AssetRipper stub（防 CS0101）。
- 方案 A（反编译接回）降级为兜底；兜底时会**撤回落位的 dll**，避免源码与 dll 同名类重复定义。
- 反编译产物只放工程外 `ModCode_Reference/`，绝不进 Assets / 最终包。

### 3. 保留并标注 `.asset` 音频 Pack Data
- `sfs_pack_prefab_export.py` 新增 `scan_pack_data_payloads()`：识别 `.asset` 里内嵌的
  base64/hex 字节流，按魔数判定音频（RIFF/OggS/ID3/fLaC/MP3）与贴图（PNG/JPG/DDS…）。
- `EXPORT_MANIFEST.json` 与 `EXPORT_README.md` 新增「含音频字节流的 Pack Data」统计。
- 导出后校验 `.asset` 拷贝前后数量一致并打印，直接回答"音频会不会丢"。

### 4. 模组资产归拢到 `<模组名>/{Audio,Sticker,Prefab,Other}`
- 新增 `organize_mod_assets()`：把**模组自己带的**资产（prefab 及其 GUID 依赖闭包）归拢到
  `Assets/<模组名>/` 下按类型分文件夹；Toolkit 原版资产留在原地。
- 移动时**连 .meta 一起搬**（否则 Unity 重生成 GUID，prefab 引用全断）。仅整理导出工程，
  合并进 Toolkit 时部件仍归一化到 `Resources/Parts`，不影响出包。

### 测试
- `test_custom_scripts.py` 改为覆盖方案 B（默认）+ 方案 A（兜底）：26 通过 0 失败。
- `test_keepalive_smoke.py` ALL PASS、`test_dedupe_cs0101.py` 20 通过 0 失败。
- 真实测试包实测：解析出 40 个自定义类、CodeAssembly 104,448 字节、依赖含 `Assembly-CSharp`。

## 2026-09-13 热修：悬空扫描误报 + 重新打包

- **修复 `repair_toolkit_dangling_refs` / `count_dangling_refs` 误报**：Unity 内置空引用占位 GUID
  `0000000000000000f000000000000000`（内置着色器如 Sprites/Default 用此 GUID + 特定 fileID 存）
  曾被当成"悬空引用"，导致清单里出现假阳性。在 `sfs_script_keep_alive.py` 顶层新增
  `UNITY_BUILTIN_NULL_GUIDS`，两处扫描均跳过该 GUID。
- 据此对用户的 Toolkit 工程（`Modding Toolkit旧版`）重跑扫描：当前**全工程 31 个 `.mat` + 所有
  prefab 内嵌材质的着色器 0 缺失**；悬空清单从 14 降到 13 条独立 GUID，且**无任何着色器悬空**
  （全是 mod 缺失的贴图/音效/PlayMaker 变量引用，属 mod 内容问题）。
- 重新打包 `SFS_Pack_Tool_v2.3.1_Embedded_GPL.exe`（RC=0，58 MB，启动冒烟 OK）。

## 2026-09-13 UI 四项修复（v2.3.1）

针对用户反馈对 `v22-CN.py` 界面与日志做四项修复，Python 源已通过 `py_compile` 与
`test_keepalive_smoke.py`（ALL PASS）验证。

### 1. 一键导出工程 ⊕ 空壳着色器/悬空引用修复 合并
- `start_export()` 的 `_run` 在 `export_project(...)` 之后**自动调用** `repair_toolkit(...)`，
  即「一键导出工程」按钮同时完成：导出 Unity 工程（脚本免挂对齐、空壳着色器替换、合并包、
  并入 Toolkit、导出后自检）＋ 清理 Toolkit 残留的 AssetRipper 空壳着色器（黑板根因）与
  悬空引用自愈扫描。
- 原先独立的「修复 Toolkit」按钮（行 4）保留，可单独再次运行。

### 2. 原始 mod 工程目录 + Toolkit 路径 合并为一个按钮
- 新增 `pick_project_dirs()`：一次点击先选 Toolkit 目录、再选原始 mod 工程目录，两个路径
  一次性写入并保存（`toolkit_dir_var` / `package_dir_var`）。
- 导出框第 6 行新增合并按钮 `选择工程目录 (Toolkit + 原始mod)`，原两个独立选择入口保留可用。

### 3. 日志补全英文（语言切换生效）
- 问题：日志此前写死中文，英文模式下仍是中文。
- 修复：
  - 新增 `_zh2en(msg)` 翻译器（标签 + 约 90 条短语），把 keepalive 内部日志的
    `[免挂]/[着色器]/[合并]/[校验]/[安装]/[修复]…` 等翻成英文。
  - 新增 `App.tlog(message)`：英文模式下先走 `_zh2en` 再落日志；所有 keepalive 调用的
    `log=` 参数与模块级 `keepalive.log` 统一改为 `self.tlog`，确保内部中文日志也翻英。
  - 导出/并入/自检流程里 11 处写死中文的 `log(f"...")` 改为键控 `self.t(...)`，新增 i18n 键：
    `log_align_done/fail`、`log_shader_fail_export`、`log_merge_done/none`、
    `log_verify_hit/missing/fail`、`install_wrote_parts/wrote_files/nothing`（zh + en 双语）。
- 结果：中文模式 = 中文，英文模式 = 英文（GUI 级日志完整翻译；keepalive 内部日志为标签 +
  关键短语英译，结构清晰可读）。

### 4. 顶部菜单栏（教程 / 关于作者 / 关于应用）
- 新增 `build_menubar()`，在窗口顶部加 `tk.Menu`：
  - **教程**：`open_tutorial()` 用浏览器打开同目录 `tutorial.html`（缺失时提示 `tutorial_missing`）。
    已新建 `tutorial.html`（深色主题使用教程，含准备/汉化/导出/合并/剥离/关于作者与 QQ 群链接）。
  - **关于作者**：弹窗显示「A Future star」，附可点击 QQ 群链接
    `https://qm.qq.com/q/3NAzgXluEo`，群号 **923038827**。
  - **关于应用**：弹窗滚动文本 `about_app_text`，介绍工具用途与实现思路。

### 修改文件
| 文件 | 改动 |
| --- | --- |
| `v22-CN.py` | 上述全部逻辑（导出+修复合并、`pick_project_dirs`、英译 `_zh2en`/`tlog`、菜单栏三窗口） |
| `tutorial.html` | 新增：教程页面 |
| `CHANGELOG.md` | 本段，新增 |

### 打包（2026-09-13）
- 用系统 Python 3.10.9 + PyInstaller 6.22.2 重建：`CODEBUDDY_SAFE_DELETE_ENABLED=0 python -m PyInstaller --noconfirm --clean SFS_Pack_Tool_v22.spec`（cwd=build_kit）。
- 产物 `dist/SFS_Pack_Tool_v2.3.1_Embedded_GPL.exe`，RC=0，58.2 MB，启动冒烟 3s 存活 = PASS。
- 已删除 `dist/` 下 4 个旧 EXE 备份（`_old` / `_prev` / `_prev2` / `_signed`）。
- 构建期仅有 `fmod.dll` 警告（UnityPy 可选音频依赖，本工具不用），不影响运行。

## v2.3.1（本次改动）

版本号已统一为 `2.3.1`：`v22-CN.py` 的 `VERSION` / `VERSION_TITLE` / 窗口标题 /
`APP_USER_MODEL_ID`，以及打包产物名 `SFS_Pack_Tool_v2.3.1_Embedded_GPL.exe`
（`SFS_Pack_Tool_v22.spec`、`build.bat`、`sign.bat`、`build_and_sign.bat` 已同步）。
图标与 spec 文件名沿用历史的 `v22` 命名，未改动。

### 核心修复：零件导入 Toolkit 后引用悬空（Odin 一片 missing / 渲染脚本 NRE）

**现象**：导入的零件在 Toolkit 里被 Odin 报上百条
`A Unity object reference has gone missing from ...`（贴图、材质、音效、Tag），
同时 `RenderSortingModule.SetDepth` 抛 `NullReferenceException`。

**根因**：AssetRipper 导出的是一个**平行 GUID 世界**。mod 复用的 SFS 原版资源
（`Metal.asset`、`Color_White.asset`、`Part 1.mat`、`Engine_2.ogg` 等），AssetRipper
会给每份都单独导出一个副本并**重新生成 GUID**，副本内部又引用平行世界里的其它 GUID。
而 Toolkit 工程里本来就有这些原版资源，GUID 是 Toolkit 自己那一套。于是：

1. 写入 Toolkit 时同名文件被「不覆盖」策略跳过 → prefab 仍指着包内那份 GUID → 悬空；
2. 就算强行拷贝也没用，副本内部的引用同样指向 Toolkit 里不存在的 GUID。

`RenderSortingModule` 的 NRE 是同一根因的次生现象——它是 `[ExecuteInEditMode]`：

```csharp
Renderer component = gameObject.GetComponent<Renderer>();
(setSharedMaterial || !Application.isPlaying ? component.sharedMaterial : component.material)
    .SetFloat(Depth, depth);   // m_Materials 悬空 → sharedMaterial 为 null → NRE
```

**修法**：新增 `remap_toolkit_duplicates()`，以 `Assets` 下的**相对路径**作为资产身份，
凡是 Toolkit 里已有同路径资产的，就把包内对它的引用全部改写成 Toolkit 那份的 GUID，
并删掉包内副本（连同 `.meta`）。判「同一个东西的副本」的做法是：二进制比字节，
文本比「把 guid 值统一打码、去掉空白」后的内容——这样只有内联引用 GUID 不同的
AssetRipper 副本能被准确识别。内容确实不同（mod 真改过）的才保留，并加 `<模组名>_`
前缀改名，既不丢 mod 改动也不跟 Toolkit 撞车。

**实测**（用户真实工程 `Engine Olders 1v` → Toolkit 旧版）：
```
修复前：引用 112 处，悬空 64 处
[对齐] 与 Toolkit 同名的原版资源 61 个 已改指 Toolkit 那份(重写引用 217 处 移除副本 122 个)
[对齐] [!] 3 个同名资源内容与 Toolkit 不同 已保留 mod 版本并改名
修复后：引用 112 处，悬空 0 处
```

**配套**：并入 Toolkit 时新增「悬空引用修复」——Toolkit 里已存在同名资产、但它引用
悬空而包里这份悬空更少时，先把原文件备份到 `<Toolkit>/_PackToolBackup/<时间戳>/`
再覆盖。判据是「悬空引用数必须下降」，只会往好的方向改。
另外修掉了 `new_parts == 0` 就不执行并入的门槛问题——部件全都已存在时恰恰最需要这次修复。

### 其它修复

- **`EndLayoutGroup: BeginLayoutGroup must be called first`**：来源是 Toolkit 工程内
  `Assets/MetaConverter/Editor/MetaConverter.cs` 的旧版（在 `OnGUI` 里直接弹模态框/抛异常，
  破坏了 IMGUI 布局栈）。已把带 `EditorApplication.delayCall` 延迟执行修复的新版同步进
  Toolkit（原文件备份为 `MetaConverter.cs.bak_<时间戳>`）。

### 修改

- **自动并入 Toolkit 时新建子目录**
  新增部件不再平铺进 `Assets/Resources/Parts/`，而是放进以模组名命名的子目录
  `Assets/Resources/Parts/<模组名>/`（文件名非法字符自动替换为 `_`，取不到名字时用 `Imported`）。
  这样玩家导入的部件和 Toolkit 自带部件不再混在一起，便于整包定位、管理与删除。

- **自动处理“黑板”零件**
  AssetRipper 反编译不了 SFS 自定义着色器，会留下带 `DummyShaderTextExporter` 标记的
  不透明 Standard 占位 shader（约 400–600 B），零件因此渲成一整块黑板且**不报错**。
  现在按 `.shader` 里声明的 Shader 名去 Toolkit 找同名真身并自动替换：
  - 导出工程：就地换成真着色器源码，**保留文件名与 GUID**，材质一行都不改，工程自身即可正确渲染；
  - 合并包：把材质 `m_Shader` 的 GUID 重指向 Toolkit 真着色器并**删掉重复文件**，
    避免 Toolkit 的 Shader 下拉里出现两个同名的 `SFS/Weird`。
  判定条件为「声明名能在 Toolkit 找到同名真身」且「GUID 不同」，再叠加
  「带占位标记」或「文件小于 8 KB」，避免误伤 mod 自制着色器；重复执行幂等。

- **修掉了空壳着色器识别的两个漏网 bug（黑板修了又复发的关键）**
  1. *UTF-8 BOM*：`Materials/Shaders/*.shader` 几乎都带 BOM（`\xef\xbb\xbf`），
     而 `^\s*Shader "..."` 正则遇到 BOM 会整体失配，导致这些真身被误判成「找不到同名真身」，
     空壳得以残留。现统一用 `utf-8-sig` 读、并在辅助函数里先 `lstrip("\ufeff")`。
  2. *同名真身被空壳顶掉*：早期版本的导入流程已经把 `Shader/SFS_*.shader` 这种占位版
     连同材质一起写进了 Toolkit（`Weird.mat`、`Part 1.mat` 等 7 个材质指过去 → 黑板）。
     清理 Toolkit 自身时「真身」和「空壳」在同一棵树里，`real` 字典按遍历顺序覆盖，
     空壳可能把真身顶掉、材质反而被指到空壳上。现把真身与空壳分两桶收录、真身优先；
     并新增 `repair_toolkit_shaders()` 专门清理**已经存在于 Toolkit 里的残留空壳**：
     把材质 `m_Shader` 重指向 `Materials/Shaders/` 下真身、删掉空壳（默认先备份到
     `<Toolkit>/_PackToolBackup/<时间戳>_stubshaders/`）。GUI 新增「修复 Toolkit 空壳着色器(黑板)」按钮。

- **消掉 Odin 的 “main object name should match the asset filename” 警告**
  导入流程对同名资源加前缀改名（如 `Engine Olders 1v_Weird.mat`），但没改文件内部的
  `m_Name`，Odin 就一直刷这行警告。新增 `sync_asset_name()`：全文件恰好一处 `m_Name`
  且与文件名不一致时，把内部名字改成文件名（只对 `.mat/.asset/.prefab` 动手，prefab 多
  `m_Name` 时不碰，避免误改子物体）；在 remap 重写材质时顺手执行，并随 Toolkit 自清理一并扫一遍。

- **`m_Name` 缩进 bug（顶格把材质写坏 → “Material {} has a missing shader” + `SetDepth` NRE）**
  Unity YAML 里 `m_Name:` 属于 `Material:` / `GameObject:` 这个**映射**，必须带缩进。
  早期 `sync_asset_name()` 的正则把整行替换成了**列 0（顶格）**的 `m_Name:`，缩进一丢，
  Unity 就**读不到它** → 主对象名变成空字符串 → 整个材质损坏 → Odin 报
  `Material {} has a missing shader`，同时 `RenderSortingModule.SetDepth` 抛
  `NullReferenceException`（该类带 `[ExecuteInEditMode]`，一打开工程就触发，崩在
  `.SetFloat` 上因为 `sharedMaterial` 为 null）。`Editor.log` 里会看到
  `Main Object Name '' does not match filename 'Engine Olders 1v_Weird'`。
  **修法**：`M_NAME_RE` 改为捕获行首缩进 `^([ \t]*)m_Name:`，`sync_asset_name()` 替换时
  原样保留缩进；顶格的情况补回 Unity 惯用的两空格。已对真实 Toolkit 执行
  `fix_asset_name_mismatches()` 把 2 个被写坏的材质
  （`Engine Olders 1v_Weird.mat`、`Engine Olders 1v_Sprite Depth.mat`）重新缩进，
  复检确认全工程 0 个顶格 `m_Name`。回归测试新增 `test_sync_asset_name_indent`（覆盖顶格补缩进 /
  缩进改名 / 已正确不动 / 多 m_Name 跳过 4 种情况）。

- **空壳判定更保守**：`fix_stub_shaders` 的「真身」索引分桶（真身优先于空壳）；

- **「修复 Toolkit」按钮新增悬空引用自愈扫描**
  旧版按钮只清 AssetRipper 空壳着色器（黑板根因）。现在额外扫描 Toolkit 里所有文本资产
  （prefab/mat/asset/unity/controller/anim）中指向**不存在 GUID** 的悬空引用——
  也就是 Odin 报 Missing(Material) / 渲染脚本 `SetDepth` NRE 的那类根因。
  新增 `repair_toolkit_dangling_refs()`：自愈需要**原始 mod 工程目录**（即 AssetRipper 导出那份）；
  对每个悬空 GUID 去包里找同名/同 GUID 原版——
  - 与 Toolkit 同名资产**等价** → 把引用改指 Toolkit 那份（去重，不重复拷入）；
  - 同名但内容不同（mod 真改过）→ 把原版**补入** Toolkit（保留原 GUID，引用自然就通）；
  - Toolkit 没有同名资产 → 同样把原版补入 Toolkit。
  找不到原版的孤儿 GUID 写进 `<Toolkit>/_PackToolBackup/<时间戳>_dangling/dangling_manifest.txt`
  交人工处理。不填原始 mod 工程目录时**只扫描+生成清单，绝不误改**。
  GUI 在导出框新增「原始 mod 工程目录（可选）」输入框；按钮文案改为
  「修复 Toolkit 空壳着色器·悬空引用」。回归测试新增 `test_repair_dangling_selfheal`
  （A 按同名重定向 / B 补入缺失资产 / C 仅扫描+清单 三场景）。
  空壳判定 `_is_stub_shader()` 从「短文件即空壳」收紧为「带 `DummyShaderTextExporter` 标记，
  或老版 AssetRipper 那套 `#pragma surface surf Standard` 样板且体积 < 8 KB 且声明名以 `SFS/` 开头」，
  避免误删 `Materials/Shaders/LineShader.shader` 这类本身就很短的真着色器。

- **包信息的“部件数”改为按 prefab 根对象统计**
  旧实现把每个 `MonoBehaviour` 都算成一个部件，而一个零件上挂着
  `ResourceModule`、`RenderSortingModule` 等多个组件，数字会虚好几倍。
  现在数 `m_Father` 为空的 Transform 对应的 GameObject（即 prefab 根）。
  另外“共 N 个部件”改为取各平台最大值而非累加，否则会被平台数再乘一遍。

### 改进

- **`remap_toolkit_duplicates` 增加「同名不同路径」匹配（防火焰材质悬空）**
  旧版只按 `Assets` 下的**相对路径**判重。mod 常把原版材质放到与 Toolkit 不同的子目录
  （如 `Materials/` 而非 `Material/`），路径对不上就不会被当作副本，prefab 仍指着包内那份
  GUID → 引用悬空（典型症状：引擎尾焰材质缺失、`RenderSortingModule.SetDepth` NRE）。
  现新增**文件名索引**作为兜底：文件基名相同即视为同一份，由等价性判断决定
  「等价→重定向+删副本」还是「内容不同→保留 mod 版并改名」。回归测试新增 `test_remap_by_name`（2h）。

### 修复

- **剥离：目标平台不在包里时直接拒绝**
  旧实现会照样写出一个只剩 `CodeAssembly`、游戏根本加载不了的 `.pack`，界面却显示“剥离完成”。

- **剥离：拒绝把结果写回源 `.pack`**
  输出路径解析后若与输入相同则中止，避免直接覆盖原模组（数据丢失）。

- **包信息：CodeAssembly 缺失时如实显示“未包含”**，且 Base64 解码失败不再让整个概览崩掉。

### 文件清单

| 文件 | 改动 |
| --- | --- |
| `sfs_script_keep_alive.py` | 新增 `_parts_subfolder_name()`、`fix_stub_shaders()`（含 `copy`/`remap` 两模式 + 自动备份）、`repair_toolkit_shaders()`、`sync_asset_name()`、`fix_asset_name_mismatches()`、`remap_toolkit_duplicates()`、`count_dangling_refs()`、`_assets_equivalent()`、`_norm_asset_text()`、`_is_stub_shader()`；`_shader_guid()` 更名 `_meta_guid()`，新增 `_read_text()`（去 BOM）；`M_NAME_RE` 改为捕获行首缩进，`sync_asset_name()` 保留/补回 YAML 缩进（防顶格把材质写坏）；`build_merge_package()` 改为子目录输出 + 着色器修复 + 同名资源对齐，报告新增 `shader_stubs/refs/deleted`、`parts_subfolder`、`dup_redirected/refs/removed/kept_diff` |
| `v22-CN.py` | 新增 `count_bundle_parts()`；`analyze_pack()` 用新口径统计并加固；`strip_pack()` 加两处兜底；导出流程新增着色器自动修复步骤；`install_into_toolkit()` 新增「悬空引用修复 + 备份」，并修掉 `new_parts==0` 不执行并入的门槛；新增「修复 Toolkit 空壳着色器(黑板)」按钮（`start_repair_toolkit`/`repair_toolkit`）；i18n 新增 12 条（中英双语） |
| `test_keepalive_smoke.py` | 新增空壳着色器修复（copy/remap/幂等/BOM 真身/真身优先）、同名资源对齐（等价重定向 / 内容不同改名保留）、Toolkit 自清理 + m_Name 同步、并入时悬空修复、包信息·剥离兜底、导出按钮接线 `run_async` 静态守护、以及 `sync_asset_name` 保留 YAML 缩进共 6 组测试 |
| `MetaConverter/Editor/MetaConverter.cs` | 已同步进 Toolkit 工程（覆盖旧版，原文件已备份） |

### 测试

```
test_keepalive_smoke.py   ALL PASS
test_custom_scripts.py    18 通过 0 失败
test_dedupe_cs0101.py     20 通过 0 失败
```

### 打包

```
python -m PyInstaller --noconfirm --clean SFS_Pack_Tool_v22.spec
```

产物：`dist\SFS_Pack_Tool_v2.3.1_Embedded_GPL.exe`
签名：把 `certs\codesign.pfx` 放好后运行 `sign.bat`（或 `build_and_sign.bat` 一步到位）。
