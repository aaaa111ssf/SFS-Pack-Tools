# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包脚本：SFS Pack Tool v2.3.6-PyQt（内置 AssetRipper 1.1.4）
# 相对路径均相对于本 spec 所在目录。

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# UnityPy 通过 importlib.resources.files("UnityPy.resources") 动态读取 lzma.tpk，
# 静态分析发现不了该包，必须显式收集包与数据文件。
hiddenimports = [
    "sfs_pack_tool_logic",      # 无界面业务层（导出/并入/剥离），函数内 import 发现不了
    "sfs_project_exporter",
    "sfs_pack_core",
    "sfs_toolkit_script_check",
    # 下面三个都是「函数内 import」的动态依赖，静态分析发现不了；
    # 漏了它们 EXE 一用到（改名/回滚/预览/日志/增量/YAML 解析）就会 ImportError。
    "sfs_assembly_rename",      # 程序集内部名改写（多模组共存），纯标准库
    "sfs_pack_toolbox",         # 回滚/预览/版本探测/日志/增量/批量
    "sfs_unity_yaml",           # 稳健 UnityYAML 引用解析（替代脆弱正则）
    "UnityPy.resources",
    "UnityPy.UnityPyBoost",
] + collect_submodules("UnityPy") + collect_submodules("tpk_ar") \
  + collect_submodules("siui")   # SiliconUI：子模块按需 import，静态分析收不全

datas = [
    ("third_party/assetripper-1.1.4", "third_party/assetripper-1.1.4"),
    ("licenses", "licenses"),
    ("SFS_Pack_Tool_v22.ico", "assets"),
    ("tutorial.html", "."),          # 内置使用教程：菜单「教程」直接打开包内 HTML
    # SiliconUI 的图标包是运行时 os.listdir 读的 .icons 文本，必须整包带上，
    # 否则界面渲染时图标全是空的（siui 内部 FileNotFoundError 会直接让 import 失败）。
    ("siui/gui/icons/packages", "siui/gui/icons/packages"),
] + collect_data_files("siui") + collect_data_files("UnityPy") + collect_data_files("tpk_ar")

a = Analysis(
    ["sfs_pack_tool_gui.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 注意：PIL（Pillow）是 UnityPy 的硬依赖，绝不能放进 excludes
    excludes=["pytest", "tests", "tkinter", "matplotlib", "pandas",
              "PIL._avif", "PIL._webp", "PIL._xcb", "PIL._tkinter_finder"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SFS_Pack_Tool_v2.3.6-PyQt_Embedded_GPL",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                # GUI 程序：无控制台窗口
    disable_windowed_traceback=False,
    icon="SFS_Pack_Tool_v22.ico",
)
