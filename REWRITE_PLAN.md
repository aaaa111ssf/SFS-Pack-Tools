# SFS Pack Tool 重写技术方案（性能优先）

> 文档性质：**决策记录 + 施工图**，不是承诺。什么时候动手另说，先把"要怎么做、代价多少、怎么验收"写清楚，免得将来又从零讨论一遍。
>
> 写于 v2.3.6-PyQt 之后，所有数字都是在开发机上实测的。

---

## 1. 现状：问题到底在哪

### 1.1 代码规模（实测）

| 模块 | 行数 | 函数 | 职责 |
| --- | ---: | ---: | --- |
| `sfs_pack_core.py` | 4305 | 107 | 解析、对齐、合并、剥离、17 适配、PackData |
| `sfs_pack_tool_gui.py` | 2314 | 125 | PyQt5 + SiliconUI 界面 |
| `sfs_pack_tool_logic.py` | 2311 | 53 | 业务流程编排、i18n、设置 |
| `sfs_project_exporter.py` | 944 | 38 | 调 AssetRipper 导出 Unity 工程 |
| `sfs_pack_toolbox.py` | 829 | 32 | 回滚/预览/增量/缓存/日志 |
| `sfs_official_keys.py` | 715 | 0 | 官方本地化键表（纯数据） |
| `sfs_unity_yaml.py` | 425 | 13 | UnityYAML 引用稳定读写 |
| `sfs_assembly_rename.py` | 395 | 17 | 程序集内部名改写 |
| `sfs_toolkit_script_check.py` | 165 | 5 | 脚本引用自检 |
| **合计** | **12403** | **390** | |

`core` 里最重的几个函数：`build_merge_package`(311)、`align_scripts_to_toolkit`(310)、`generate_pack_data`(217)、`restore_custom_scripts`(216)、`repair_toolkit_dangling_refs`(212)。

### 1.2 耗时实测

| 场景 | 现在 | 备注 |
| --- | ---: | --- |
| 单文件 EXE 冷启动 | **48s** | 每次解压 118MB + 杀软扫描 |
| 安装版启动 | **3.36s** | 其中 Python 层 2.38s |
| └ Python 导入 | 1.50s | PyQt5 + siui ≈ 1.3s |
| └ 建界面 | 0.68s | 三个页面一次性构建 |
| └ 首帧 | 0.10s | |
| 扫描 19.2MB 包 | **6.71s** | 见下面的重复加载问题 |
| └ `collect_monoscript_classes` | 3.31s | 4 个平台各 load 一次 |
| └ `build_pack_prefab_script_map` | 3.45s | 又 load 了 4 次 |
| └ `import UnityPy` | 2.44s | 一次性 |
| 解出 CodeAssembly | 0.27s | 104KB，纯 base64 |
| 导出 Unity 工程 | 分钟级 | **AssetRipper 外部进程，占大头** |

### 1.3 三个结论

1. **启动慢的主因已经解决**（48s → 3.36s 靠换安装型），剩下的 2.4s 里 1.3s 是 Qt 初始化。
2. **解析层有明确的浪费**：同一个包被 `UnityPy.load` 了 **8 次**（4 平台 × 2 个分析函数），
   每次都要解 5MB 左右的 bundle 并建对象树。这是纯 Python 也能先修的，重写时更该一次建模型。
3. **导出的瓶颈不在我们代码里**，在 AssetRipper（独立 .NET 进程）。

---

## 2. 目标与非目标

### 目标（可验收）

| 指标 | 现状 | 目标 |
| --- | ---: | ---: |
| 冷启动到可交互 | 3.36s | **< 0.6s** |
| 扫描 19.2MB 包 | 6.71s | **< 1.5s** |
| 扫描 100MB 包 | 估 20s+ | **< 6s** |
| 导出期间 UI 响应 | 可用（后台线程） | 不卡、进度连续 |
| 峰值内存 | 未测（估 600MB+） | **< 400MB** |
| 单文件分发体积 | 118MB | < 80MB |

### 非目标

- **不改功能语义**：现有的对齐规则、合并闸门、剥离行为、17 适配规则全部照搬，不许"顺便重构业务"。
- **不重做视觉**：现有深色毛玻璃风格保留，只换实现。
- **不替换 AssetRipper**：它已经把 Unity 工程导得很好了，重写它不划算。
- **不追求跨平台可用性**（可作为加分项，不作为验收条件）。

---

## 3. 技术选型

| 方案 | 启动 | 解析性能 | 工作量 | 风险 | 结论 |
| --- | ---: | --- | ---: | --- | --- |
| **C# .NET 8 + Avalonia** | 0.3–0.6s | **优**（AssetsTools.NET 原生解析） | 20–30 人日 | 中（视觉要重做） | **推荐** |
| C# .NET 8 + WPF | 0.3–0.5s | 优 | 20–30 人日 | 中（仅 Windows） | 备选 |
| **Rust + GPUI** | **0.1–0.3s** | **差**（无成熟 Unity 解析库） | 40–60 人日 | **高** | 不推荐（见 3.2） |
| Rust + Tauri | 0.2s 壳 + WebView 0.3–0.8s | 中 | 30–40 人日 | 高 | 不建议 |
| C++ / Qt | 0.2s | 优 | 40+ 人日 | 高 | 不建议 |
| 继续 Python（微优化） | 2.0–2.4s | 差（解释执行 + 生成类） | 1–2 人日 | 低 | **短期先做** |

### 为什么是 C# + Avalonia

1. **解析层可以直接换掉 UnityPy**：`AssetsTools.NET` 是同类库的 C# 实现，读 Unity bundle 的
   TypeTree 比 UnityPy 快一个量级，而且能流式读，不必把整个对象树建出来。
2. **AssetRipper 本来就是 .NET**：可以继续用 CLI 子进程，将来也能直接引它的库，省一次进程启动。
3. **启动快**：Avalonia 应用冷启动通常 0.3–0.6s，比 PyQt5 少一个 Python 解释器 + 1.3s 的 Qt 初始化。
4. **单人可维护**：强类型 + 编译期检查，这种"几千行字符串/GUID 操作"的代码里能少踩很多坑。
5. **代价明确**：siui 那套圆角毛玻璃控件没有现成替代，要在 Avalonia 里自己画（Fluent 主题 + 自定义样式），
   这是整个重写里最费时的部分。

### 3.2 为什么不选 Rust + GPUI

先说它好的地方，免得显得在硬拗：

- **启动和渲染确实顶级**。GPUI 直接把 UI 当 GPU 着色器的输入画，没有 DOM、没有布局重排，
  冷启动 0.1–0.3s、常驻内存比 Electron 少一个数量级——Zed 就是靠这个立身的。
- **平台已经不是问题**。GPUI 随 Zed 1.0（2026-04）在 macOS(Metal) / Linux(Vulkan) / Windows(D3D12)
  三平台都跑生产环境了，Windows 这条线今年才真正成熟。
- **它是 Apache-2.0 开源的**，拿来写别的桌面应用没有许可证障碍。

但放到**这个项目**上，有三个绕不过去的坎：

1. **Rust 没有成熟的 Unity bundle / TypeTree 解析库。**
   这是决定性的一条。Python 有 UnityPy，C# 有 AssetsTools.NET，而 Rust 侧基本得自己写：
   bundle 解压（LZ4/LZMA）+ SerializedFile + TypeTree + 逐类字段读取。
   我们自己那层"读包 → 读 MonoScript → 读 MonoBehaviour 字段"的代码约 1000–1500 行 Python，
   换成 Rust 是**从零实现一个序列化格式解析器**，保守 3–5 周，且没有对照物可以验错。
2. **GPUI 是 Zed 的内部框架，不是稳定产品库。**
   它没有对外承诺的 API 稳定性，版本间破坏性改动频繁，文档和示例远少于 Avalonia；
   控件生态（表格、树、对话框、文件选择、无障碍）几乎为零，等于全自绘。
   对一个人维护的工具来说，这是持续的维护税。
3. **中文输入法与文本排版要单独验证。**
   Zed 的文本渲染很强，但编辑器的输入路径和"表单式应用"不同；
   IME 组合、选区、右键菜单这些在 GPUI 里都要自己趟一遍。
   这是**必须先花 1 人日做技术验证**的事项，一旦不通，前面的 UI 工作全部作废。

**结论**：Rust+GPUI 适合"把 UI 做到极致"的产品，但本项目的瓶颈在**包解析 + AssetRipper**，
换 UI 拿不到端到端收益，却要付一次全量重写 + 生态自建的代价。

如果你确实想要 Rust 的性能，务实的组合是：
**Rust + GPUI 做壳，解析走 C# 侧车（AssetsTools.NET）**——但这等于同时维护两套运行时，
比纯 C# 更难，所以只在"UI 是核心卖点"时才值得。

> 顺带纠正一个常见预期：C# 并不慢。.NET 8 用 NativeAOT 发布后启动也能到 0.1–0.2s，
> 体积 30–50MB；它真正的优势是**生态里有对口的解析库**，而不是语言本身。

---

## 4. 架构

```
SfsPackTool.sln
├─ SfsPack.Core            纯逻辑，零 UI 依赖，可单测
│   ├─ Pack/               .pack 读写、平台 bundle、CodeAssembly
│   │   ├─ PackArchive.cs  一次加载，多用途（解决 8 次重复 load）
│   │   ├─ PackScanner.cs  类名/脚本/平台统计
│   │   └─ PackMetadata.cs PackData 读出
│   ├─ Unity/              Unity 资源封装（基于 AssetsTools.NET）
│   │   ├─ UnityYaml/      稳定读写：按 token 定位，逐字符保留原格式
│   │   ├─ GuidIndex.cs    类名 ↔ GUID、meta 索引
│   │   └─ MetaFile.cs     .meta 读写 + AssetBundle 标签
│   ├─ Scripts/            脚本对齐、DLL 方案、ModCode 方案、剥离
│   ├─ Merge/              合并包、闸门、冲突预检、去重
│   ├─ Export/             AssetRipper 调用与后处理
│   └─ Translation/        汉化提取/写回/键过滤
├─ SfsPack.Host             业务编排（原 logic.py）：流程、设置、i18n、日志
├─ SfsPack.App              Avalonia 界面（原 gui.py）
└─ SfsPack.Tests            xUnit：golden 对比 + 单元测试
```

**进程边界**：AssetRipper 保持子进程（`dotnet run` 或直接 exe），stdout 转发到日志。
这样即使它崩了也不会带走主程序。

---

## 5. 模块映射

| Python | C# | 迁移难度 | 备注 |
| --- | --- | --- | --- |
| `sfs_pack_core.py` 解析段（~1000 行） | `Core/Pack/*` + `Unity/*` | 中 | 换 AssetsTools.NET，字段名要重新对 |
| `sfs_pack_core.py` 对齐/合并/剥离（~2500 行） | `Core/Scripts/*` + `Core/Merge/*` | **高** | 规则最密，坑最多，见第 6 节 |
| `sfs_unity_yaml.py` | `Unity/UnityYaml/*` | 中 | 不能换成通用 YAML 库 |
| `sfs_project_exporter.py` | `Core/Export/*` | 低 | 主要是参数拼装 + 进程调用 |
| `sfs_assembly_rename.py` | `Core/Scripts/AssemblyName.cs` | 低 | 二进制补丁，逻辑独立 |
| `sfs_pack_toolbox.py` | `SfsPack.Host/Toolbox/*` | 低 | 文件/索引/缓存，纯 IO |
| `sfs_pack_tool_logic.py` | `SfsPack.Host/*` | 中 | i18n 表可直接搬 |
| `sfs_pack_tool_gui.py` | `SfsPack.App/*` | **高** | 视觉重做 |
| `sfs_official_keys.py` | 嵌入资源 | 低 | 纯数据，可直接转 JSON |

---

## 6. 关键算法迁移清单（坑都在这）

按"重写时最容易做错"排序：

1. **UnityYAML 稳定重写**（`sfs_unity_yaml.py`）
   - 现在的实现是按 token 扫描 `m_Script` / `guid` / `fileID`，只替换值，**其余字符一字不动**。
   - **禁止**用通用 YAML 库：会重排键序、丢注释、改缩进，Unity 导入时可能直接判定资源损坏。
   - 重写仍要走"定位 + 原位替换"，不要序列化。
2. **多类文件 → 类名映射**（`scan_script_meta`）
   - 一个 `.cs` 里可能声明多个顶层类（老版本把 `SoundEffect`/`Sound` 塞在 `SF_Misc.cs`），
     只登记文件主类会漏，导致音频 `.asset` 的 `m_Script` 不改写 → 加载成 null。
3. **结构对齐**（`build_pack_prefab_script_map` + `resolve_export_script_guids`）
   - 包里 `MonoScript` 有 `m_ClassName` / `m_AssemblyName`，`MonoBehaviour.m_Script` 是 PPtr；
   - 导出工程里 AssetRipper **可能一个 stub 都不生成**，这时只能靠 `.pack` 结构反推 GUID ↔ 类名。
   - 两边都要支持：stub 优先，结构兜底。
4. **合并闸门**（`unresolved_guids`）
   - 重写后仍有 GUID 找不到脚本 → 拒绝合并 + 落 `UNRESOLVED_SCRIPTS.md`。
   - 剥离时要把被剥离的 GUID 从清单里移除，否则会误拦整包。
5. **自定义脚本两套方案必须互斥**
   - DLL 方案（`Assets/Plugins/<内部名>.dll`）与反编译源码方案（`Assets/Scripts/ModCode`）**只能留一套**，
     同时存在 → 同名类重复定义 CS0101。
6. **剥离的三条关键事实**
   - prefab 上的自定义组件是「**指向 mod dll 的 guid + 不同 fileID**」，
     按类名查 GUID 一个都匹配不到 → 必须先按内容 sha256 比对出 dll、取它的 meta guid；
   - 摘组件要删整段 `--- !u!114 &id` 文档，**并清掉 GameObject `m_Component` 里的挂点**；
   - 自定义脚本的数据资产（`.asset` 的 m_Script 指向自定义类）必须删，否则 Unity 报 Broken Asset。
7. **1.7 引擎/助推器字段修复**
   - Engine：`isVacuum` / `multipleNozzles` / `heatHitboxes[]` / `heatHitbox`，
     `heatHitbox` 兜底 = `heatHolder` 的**首个子物体**，且**仅当 `!multipleNozzles`**；
   - Booster：`boosterOn` / `setDensity` / `heatHitbox`，兜底 = `heatHolder` **自身**；
   - `vacuumMaxPressure` 是 `const`，**不序列化，不要补**。
   - 这些规则已经从官方 1.7 内测版 dll 反编译核对过，别凭记忆改。
8. **汉化写回只改显示字段**（`TranslationVariable`）
   - `TranslatableName: None` 会被 Unity 解析成 null，写回时判空；键过滤规则在 `sfs_official_keys.py`。

---

## 7. 性能设计要点

1. **PackArchive 一次加载**：当前 scan 一次要 load 8 次（4 平台 × 2 函数）。重写时按
   `PackArchive.Load(pack)` → 内存里保留 platform → bundle → typetree 的惰性索引，各分析函数共享。
   这一条单独就能把 6.7s 压到 2s 以内。
2. **流式处理大工程**：3000+ prefab 不要一次性读进内存，按文件流式读、流式写、就地替换。
3. **并行**：prefab/GUID 重写天然可分片，用 `Parallel.ForEach`，注意日志顺序要串行化。
4. **零拷贝**：bundles 用 `Span<byte>` / `MemoryMappedFile`；base64 解码直接到 buffer。
5. **UI 与 Core 用 Channel 通信**：进度用 `IProgress<ProgressEvent>`，日志走有界 Channel，
   避免高频日志把 UI 线程打满（现有 Python 版就吃过这个亏）。
6. **启动**：Avalonia 用编译绑定（`x:CompileBindings`），首屏只建当前页，其余延迟到切页时构建。

---

## 8. 里程碑与工作量

| 阶段 | 内容 | 人日 | 验收 |
| --- | --- | ---: | --- |
| **M0** | 立即可做的微优化（不重写）：UnityPy.load 缓存、启动闪屏、延迟建页 | 1–2 | 扫描 <4s，体感"秒开" |
| **M1** | 骨架：sln/项目/CI/golden 测试框架 | 2 | `dotnet build` + 空窗口 <0.6s |
| **M2** | Pack 解析（只读）：平台、bundle、MonoScript、PackData | 4 | 与 Python 版扫描结果逐条一致 |
| **M3** | UnityYAML 稳定读写 + GUID 索引 | 3 | 对同一工程重写 0 字节差异 |
| **M4** | 对齐 / 合并 / 剥离 / 17 适配 | 8 | golden 工程输出与 Python 版等价 |
| **M5** | 导出链路（AssetRipper 子进程 + 后处理） | 3 | 端到端跑通 3 个真实包 |
| **M6** | Avalonia 界面（复刻现有视觉 + 三个页面） | 6 | 功能对等，无回归 |
| **M7** | 打包：单文件 + onedir + NSIS Setup | 2 | 启动 <0.6s，体积 <80MB |
| | **合计** | **29–31 人日** | |

按"每天有效 2 小时"算，约 **3–4 个月**；全职约 6 周。

---

## 9. 质量与验收

### 9.1 Golden 测试（最重要）

现有 Python 版就是**唯一真值来源**。做法：

1. 固定一组真实包（见 9.2），用 Python 版跑出完整输出（导出工程 + 合并包 + 日志）；
2. 把输出里的 GUID 打码、绝对路径打码、时间戳抹掉，存成基准快照；
3. C# 版对同样输入产出，**逐文件比对**（prefab 逐行、`.meta` 逐个 guid）。

只要快照一致，就认为行为对等。不一致的地方必须能解释，不许"看着差不多"。

### 9.2 回归包集合

| 包 | 特征 | 覆盖点 |
| --- | --- | --- |
| `Power System and Thermal Management System Test Package.pack` | 19.2MB，CodeAssembly 104KB，10 个自定义类 | 剥离、DLL 方案、大包解析 |
| `Engine Olders.pack` | 1.7 老引擎，无自定义脚本 | 17 字段修复、普通合并 |
| `Artemis Program.pack` | 有自定义类、60+ prefab | 结构对齐（无 stub 场景） |
| `heatshieldtiles.pack` | 多平台重复 | 单平台解码、去重 |
| 一个 1.6 时代的包 | 老格式 | 向后兼容 |

### 9.3 性能基准

把第 1.2 节的表变成脚本，每次构建跑一遍，回归超过 20% 就拦。

---

## 10. 迁移策略

**不要大爆炸式替换**，按能力切片、双实现并行：

1. 先做 M0 微优化，让现有版本立刻变好（不依赖重写）；
2. M1–M3 期间 Python 版继续发布，C# 版只在开发机上跑；
3. M4 起用 golden 测试卡住等价性；
4. 切换顺序：**解析只读 → 导出 → 合并 → 界面**，界面永远最后换（视觉骂声最大、收益最小）；
5. 保留 Python 版至少一个大版本，出问题能立刻回退。

---

## 11. 风险与止损

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| Avalonia 复刻 siui 视觉成本超预期 | 高（占 6 人日） | 先用 Fluent 主题近似，视觉细节后补；必要时改用更朴素的卡片布局 |
| AssetsTools.NET 与 UnityPy 行为差异 | 高（解析结果不一致） | 先用 5 个包做字段级 diff，差异点逐个建单元测试 |
| 规则迁移漏坑（CS0101 / 挂空） | 高（用户工程被搞坏） | golden 测试 + 合并闸门保留 + 开关可回退 Python 版 |
| 单人长期维护断层 | 中 | 文档即本文档 + CHANGELOG 保留决策理由 |
| 重写期间原版没人修 bug | 中 | M0 只做微优化，功能冻结期不超过 2 周 |
| （若走 Rust）GPUI 的中文 IME / 表单控件不达标 | 高 | **先做 1 人日 spike**，不通就立刻放弃这条路 |

**止损线**：M4 结束（约 17 人日）如果 golden 通过率 <80%，就停止重写、只保留 M0 优化。

---

## 12. 现在就能做、不用等重写的三件事

按性价比排序，随时可以插进来做：

1. **UnityPy.load 缓存**（约 0.5 人日）
   同一个包在一次扫描里被 load 了 8 次。加一个 `(pack, platform) → env` 的缓存，
   扫描 19.2MB 包预计从 **6.71s → 3.5s 左右**。
2. **启动闪屏**（约 0.3 人日）
   窗口 0.2s 内出现，主界面在背后加载。体感从 3.36s 变"点开就有反应"。
3. **延迟构建非当前页**（约 0.5 人日）
   现在三个页面一次性建完（0.68s），改成切页时再建，冷启动再省 0.3–0.4s。

这三条做完，现有版本已经接近"够用"，重写的紧迫性会进一步下降——这也是我建议先做它们的原因。

---

## 附：一句话总结

> 重写值不值，取决于你要不要"长期把这事做下去"。
> 只是自己用 → M0 三条优化够了；要发布给一群人长期维护 → C# + Avalonia 是对的方向，
> 30 人日、3–4 个月，风险和收益都比 Rust/重写 AssetRipper 更可控。
