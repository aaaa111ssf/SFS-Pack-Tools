# M0 施工单：启动画面 / 解析缓存 / 延迟建页 / C# 解析桥

> 用途：晚上照单执行。每条都写清楚**改哪个文件、哪一行、怎么验、退回怎么做**，不需要再重新调研。
>
> 依据：`REWRITE_PLAN.md` 第 12 节的三条即时优化 + 第 5 节的解析层替换。

---

## 0. 目标与本轮范围

| 任务 | 收益（预期） | 工程量 | 今晚做？ |
| --- | --- | ---: | --- |
| A. `UnityPy.load` 缓存 | 扫描 19.2MB 包 **6.71s → ~3.5s** | 0.5 人日 | ✅ |
| B. 启动画面 | 窗口 **0.2s 内出现**（体感秒开） | 0.3 人日 | ✅ |
| C. 延迟建页 | 冷启动再省 **0.3–0.4s** | 0.5 人日 | ✅ |
| D. 解析层换 C# | 扫描 **< 1.5s** | 2–4 人日 | ❌ 另排，先出设计 |

做完 A+B+C，现有版本体感接近"够用"；D 是结构性改造，单独立项，别和前三件混在一个提交里。

---

## 1. 任务 A：`UnityPy.load` 缓存

### 现象

一次 `scan_pack()` 会把同一个包解 **8 次**：

- `collect_monoscript_classes()` → 4 个平台各 `UnityPy.load` 一次
- `build_pack_prefab_script_map()` → 又 4 次

每次都要解 ~5MB bundle 并建对象树，这是扫描 6.71s 的主因。

### 调用点（改这 8 处）

| 文件 | 行 | 上下文 |
| --- | --- | --- |
| `sfs_pack_core.py` | 276 | `collect_monoscript_assemblies` |
| `sfs_pack_core.py` | 339 | 同类读取（path_id 收集） |
| `sfs_pack_core.py` | 420 | `collect_monoscript_pathids` |
| `sfs_pack_core.py` | 571 | prefab 脚本布局读出 |
| `sfs_pack_core.py` | 3130 | `_read_pack_metadata`（PackData） |
| `sfs_pack_tool_logic.py` | 1225 | `analyze_pack` 平台遍历 |
| `sfs_pack_tool_logic.py` | 1284 | 同上（第二遍） |
| `sfs_pack_tool_logic.py` | 1353 | 单包解析 |

### 做法

在 `sfs_pack_core.py` 顶部加一个模块级缓存（**不要加锁**，现有调用都在同一线程；将来并行再说）：

```python
# 同一个包的同一个平台只解一次，扫描一次能省 3 秒左右
_ENV_CACHE: dict[tuple[str, int], object] = {}
_ENV_CACHE_MAX = 4          # 只留最近 4 个包，避免大包把内存撑爆


def load_env_cached(pack_path, platform: str, raw: bytes):
    """读 bundle；同一个包同一平台复用已解析的环境。"""
    key = (str(pack_path), id(raw))
    hit = _ENV_CACHE.get(key)
    if hit is not None:
        return hit
    import UnityPy
    env = UnityPy.load(raw)
    if len(_ENV_CACHE) >= _ENV_CACHE_MAX:
        _ENV_CACHE.pop(next(iter(_ENV_CACHE)))
    _ENV_CACHE[key] = env
    return env
```

要点：

- **key 用 `(pack_path, id(raw))`**：不同平台是不同 bytes 对象，天然区分；
  用 `id()` 而不是 hash(bytes)，避免对大 bytes 做哈希（几百 KB 也要几十 ms）。
- **缓存上限 4**：一个包 4 个平台正好；换包时淘汰最早的，防止内存线性增长。
- **别缓存 `env.objects` 的遍历结果**——UnityPy 的对象是惰性的，缓存 env 就够。

然后把这 8 处 `UnityPy.load(...)` 换成 `load_env_cached(...)`，参数按原样传。

### 验收

```bash
python -c "import time,sfs_pack_core as c; from pathlib import Path; \
t=time.perf_counter(); c.scan_pack(Path(r'D:/Power System and Thermal Management System Test Package.pack'), None, log=lambda *a:None); \
print(f'{time.perf_counter()-t:.2f}s')"
```

- 改前基线：**6.71s**
- 目标：**≤ 3.8s**
- 同时跑 `test_core_smoke.py` 必须 ALL PASS（解析结果不能变）

### 回退

单文件改动，`git diff` 直接 revert；缓存的 key 不出包路径，没有持久化污染。

---

## 2. 任务 B：启动画面

### 现状

`main()` 里是先 `App()`（0.68s 建三个页面）再 `window.show()`，用户双击后有一段时间完全没反应。

### 做法

在 `sfs_pack_tool_gui.py` 的 `main()` 里：

1. `QApplication` 建好后**立刻**显示一个无边框的小窗口（320×180），中间放图标 + 「正在加载…」；
2. 用 `QTimer.singleShot(0, ...)` 把 `App()` 的构造推到事件循环里，让闪屏先绘制出来；
3. `App()` 构造完成后 `splash.close()`，再 `window.show()`。

```python
def main() -> int:
    ...
    app = QApplication(sys.argv)
    splash = SplashScreen()          # 无边框，居中，带版本号
    splash.show()
    app.processEvents()              # 让它真的画出来

    holder = {}

    def build() -> None:
        holder["win"] = App()
        holder["win"].show()
        splash.finish(holder["win"])   # 自动关闭闪屏

    QTimer.singleShot(0, build)
    return app.exec_()
```

注意事项（都是踩过的）：

- **`test`/offscreen 环境**：`QT_QPA_PLATFORM=offscreen` 时闪屏别调用 `raise_()`，否则会抢焦点导致脚本挂住；
- **异常路径**：`App()` 里如果抛异常（比如上次修过的 `settings.json` 坐标问题），
  `build()` 要 `try/except` 把闪屏关掉再抛，否则用户会看到闪屏卡死；
- **别在闪屏里做重活**：只画静态图 + 文字，不加载图标包（`_iconpack()` 首次调用就要 100ms+）；
- 有 `--silent` / 自动测试入口时跳过闪屏（加个环境变量 `SFS_NO_SPLASH=1`）。

### 验收

- 双击到有窗口出现：目标 **≤ 0.3s**（现在 3.36s 全是白屏等待）
- 主窗口出现后闪屏必须消失，不能残留置顶窗口
- 用 `_startup_time.py` 那种脚本量一下，别靠感觉

---

## 3. 任务 C：延迟建页

### 现状

`build_ui()` 里一次性把三页都建出来：

```python
self.pages.addWidget(self._wrap_scroll(self._page_restore()))
self.pages.addWidget(self._wrap_scroll(self._page_translate()))
self.pages.addWidget(self._wrap_scroll(self._page_strip()))
```

三页各有一批控件 + 图标，实测 0.68s。

### 做法

1. 三页先各放一个**空的占位 QWidget**（只设背景色，不建控件）；
2. 记录 `self._built_pages: set[int]`；
3. `switch_page()` 和 `build_ui()` 里调用 `_ensure_page(index)`：第一次访问时才真正构建并替换占位页；
4. `build_ui()` 结束时只为**当前页**调 `_ensure_page`，其余留着下次。

```python
def _ensure_page(self, index: int) -> None:
    """第一次切到某页才真正建它，冷启动少建两页。"""
    if index in self._built_pages:
        return
    builders = {0: self._page_restore, 1: self._page_translate, 2: self._page_strip}
    real = self._wrap_scroll(builders[index]())
    placeholder = self.pages.widget(index)
    self.pages.insertWidget(index, real)
    self.pages.removeWidget(placeholder)
    placeholder.deleteLater()
    self._built_pages.add(index)
```

注意：

- `build_ui()` 现在开头会 `while self.pages.count(): 清空`，切语言/主题重建时要**重置 `_built_pages`**；
- 页面里有跨页引用（比如日志面板）的控件要先确认不依赖其它页；
- 侧边栏的选中态在 `switch_page` 里已经处理，不用动。

### 验收

- `App()` 构造：0.68s → **≤ 0.4s**
- 三页都能正常切、切过去不闪白、切语言后仍然正常
- `test_core_smoke.py` 里的界面冒烟用例要过

---

## 4. 任务 D：解析层换 C#（另排，先定设计）

### 为什么单独做

它动的是"读包"这条主干，一旦出错影响所有功能（导出/合并/剥离/汉化）。和 A/B/C 混在一起提交，
出问题不好定位，也不好回退。

### 架构：旁挂式解析桥（不动 UI）

```
SFS Pack Tool (Python/PyQt)
        │  子进程 + JSON
        ▼
sfs_parse.exe  (C# / .NET 8 / AssetsTools.NET)
   scan | script-map | packdata | extract-code
```

**为什么用子进程而不是 pythonnet：**

- 崩了不带走主程序；
- 不需要在 PyInstaller 里搞定 .NET 运行时加载；
- 参数/结果都是 JSON，好测、好 mock。

### JSON 契约（先定死，两边照写）

```json
{
  "pack": "xxx.pack",
  "platforms": ["WindowsBuild", "AndroidBuild", "MacBuild", "IOS_Build"],
  "classes": ["Part", "EngineModule", "..."],
  "custom_classes": ["PowerModule", "ThermalModule"],
  "scripts": [
    {"platform": "WindowsBuild", "path_id": 1234, "class": "PowerModule", "assembly": "AssetsofIce"}
  ],
  "packdata": {"display_name": "xxx", "version": "1.0", "author": "yyy", "show_icon": false}
}
```

Python 侧入口（新文件 `sfs_parse_bridge.py`）：

```python
def scan(pack_path) -> dict | None:
    """有 C# 解析器就用它，没有返回 None，调用方退回 UnityPy。"""
```

**必须保留回退**：环境变量 `SFS_FORCE_PY_PARSE=1` 或 exe 缺失时，走现在的 UnityPy 路径。
这样至少能用"同一个包、两条路径、结果 diff"来验证 C# 写的对不对。

### 打包

- C# 侧 `dotnet publish -r win-x64 -p:PublishAot=true` → 单文件 20MB 以内；
- PyInstaller 里作为 `datas`/`binaries` 随包带出，放 `third_party/parse/`；
- 首次运行校验版本号，不匹配就回退 Python 路径。

### 验收

- `Power System and Thermal Management System Test Package.pack`：扫描 **< 1.5s**
- 与 Python 版扫描结果逐条一致（类集合、custom_classes、script 映射、PackData 四块）
- 100MB 以上的包不 OOM，峰值内存 < 400MB

### 预估

| 步骤 | 人日 |
| --- | ---: |
| 骨架 + JSON 契约 + 平台枚举 | 0.5 |
| MonoScript / MonoBehaviour 读取（AssetsTools.NET） | 1.0 |
| PackData + CodeAssembly 提取 | 0.5 |
| Python 侧桥接 + 回退 + diff 工具 | 0.5 |
| 打包与 AOT | 0.5 |
| **合计** | **3.0** |

---

## 5. 今晚的执行顺序与时间盒

| 顺序 | 任务 | 时间盒 | 完成标志 |
| ---: | --- | --- | --- |
| 1 | A. load 缓存 | 40 min | 扫描 ≤ 3.8s，回归 ALL PASS |
| 2 | B. 启动画面 | 40 min | 0.3s 出画，异常路径不卡死 |
| 3 | C. 延迟建页 | 40 min | App() ≤ 0.4s，三页可切 |
| 4 | 重打包 + 实测 | 30 min | 安装版启动 ≤ 2.5s，功能抽检通过 |
| 5 | 提交 | 10 min | 一个提交，message 写清三项与数字 |

**原则**：A/B/C 各自独立提交也可以，但**都必须先跑回归**。任何一项超时 1.5 倍就先放着，别把三件都做成半成品。

---

## 6. 验收总表（改完一次性对）

| 指标 | 改前 | 目标 | 怎么测 |
| --- | ---: | ---: | --- |
| 扫描 19.2MB 包 | 6.71s | ≤ 3.8s（A）；≤ 1.5s（D 完成后） | 上面的命令行片段 |
| 闪屏出现 | 无 | ≤ 0.3s | 录制/时间戳 |
| App() 构造 | 0.68s | ≤ 0.4s | `_startup_time.py` |
| 安装版启动 | 3.36s | ≤ 2.5s | 同上 |
| 回归 | ALL PASS | 不许有失败 | `test_core_smoke.py` + `test_translation_writeback.py` |

---

## 7. 回滚

- A：删掉 `load_env_cached` 与 8 处替换，恢复 `UnityPy.load`；
- B：`main()` 里去掉 splash 分支，保留 `SFS_NO_SPLASH=1` 兜底；
- C：`build_ui()` 恢复三页直建，删 `_ensure_page`；
- D：`sfs_parse_bridge.scan()` 永远返回 None 即完全回退 Python 路径（**这是设计上的保险丝**）。

---

## 8. 风险

| 风险 | 应对 |
| --- | --- |
| 缓存 env 后内存涨（大包 × 4 平台） | 上限 4 个、按插入顺序淘汰；跑 100MB 包看峰值 |
| 闪屏挡不住真实卡顿反而更尴尬 | 闪屏必须在 0.2s 内出现；若 App() 仍要 2s，考虑把"扫描/选包"也延迟 |
| 延迟建页导致跨页引用取不到 | 先 grep 三页里对彼此的引用，必要时保留共享对象 |
| C# 解析结果与 UnityPy 有偏差 | 先写 diff 工具，用 5 个真实包对齐，再切默认路径 |
