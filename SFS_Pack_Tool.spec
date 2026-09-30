# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包脚本：SFS Pack Tool v2.3.3（内置 AssetRipper 1.1.4）
# 相对路径均相对于本 spec 所在目录。

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# UnityPy 通过 importlib.resources.files("UnityPy.resources") 动态读取 lzma.tpk，
# 静态分析发现不了该包，必须显式收集包与数据文件。
hiddenimports = [
    "sfs_project_exporter",
    "sfs_pack_core",
    "sfs_toolkit_script_check",
    "UnityPy.resources",
    "UnityPy.UnityPyBoost",
] + collect_submodules("UnityPy") + collect_submodules("tpk_ar")

datas = [
    ("third_party/assetripper-1.1.4", "third_party/assetripper-1.1.4"),
    ("licenses", "licenses"),
    ("SFS_Pack_Tool_v22.ico", "assets"),
    ("tutorial.html", "."),          # 内置使用教程：菜单「教程」直接打开包内 HTML
] + collect_data_files("UnityPy") + collect_data_files("tpk_ar")

a = Analysis(
    ["sfs_pack_tool_gui.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tests"],
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
    name="SFS_Pack_Tool_v2.3.3_Embedded_GPL",
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
