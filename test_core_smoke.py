#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SFS Pack Tool 离线回归测试（无需真实 .pack / AssetRipper）。

用桩件替代 UnityPy，在临时目录里搭最小工程验证核心链路：
  1. 脚本免挂对齐：删 stub -> 整拷 Toolkit 脚本 -> 重写 .prefab/.asset 的 m_Script GUID
  2. 合并包：新增部件归一化到 Assets/Resources/Parts，且不含 .cs
  3. 新增部件同名去重
  4. 并入 Toolkit 时绝不覆盖既有文件

运行：python test_core_smoke.py
"""
from __future__ import annotations

import base64
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

BUILD_KIT = Path(__file__).resolve().parent
sys.path.insert(0, str(BUILD_KIT))

TOOLKIT_PART = "a" * 32
TOOLKIT_BASE = "b" * 32
STUB_IN_SCRIPTS = "c" * 32
STUB_IN_MONOSCRIPT = "d" * 32
MOD_DLL_GUID = "68295d573e80e1c18ab7ad250963a526"


class Result:
    def __init__(self) -> None:
        self.ok = True

    def check(self, label: str, cond: bool) -> None:
        print(f"  [{'OK ' if cond else 'FAIL'}] {label}")
        if not cond:
            self.ok = False


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def unity_meta(guid: str) -> str:
    return f"fileFormatVersion: 2\nguid: {guid}\nMonoImporter:\n  externalObjects: {{}}\n"


def install_fake_unitypy(dirpath: Path, classes: list[str]) -> None:
    write(dirpath / "UnityPy.py", (
        "class _Obj:\n"
        "    def __init__(self, cls):\n"
        "        self.type = type('T', (), {'name': 'MonoScript'})()\n"
        "        self._cls = cls\n"
        "    def read(self):\n"
        "        return type('MS', (), {'m_ClassName': self._cls})()\n"
        "class _Env:\n"
        "    def __init__(self, objs): self.objects = objs\n"
        f"def load(raw):\n"
        f"    return _Env([_Obj(c) for c in {classes!r}])\n"
    ))
    sys.path.insert(0, str(dirpath))


def make_toolkit(root: Path) -> Path:
    toolkit = root / "Toolkit"
    scripts = toolkit / "Assets" / "Scripts"
    write(scripts / "Part.cs", "// class FakeInComment\npublic class Part : Base {}\n")
    write(scripts / "Part.cs.meta", unity_meta(TOOLKIT_PART))
    write(scripts / "Base.cs", "public class Base {}\n")
    write(scripts / "Base.cs.meta", unity_meta(TOOLKIT_BASE))
    return toolkit


def make_pack(root: Path) -> Path:
    pack = root / "mod.pack"
    write(pack, json.dumps({"WindowsBuild": base64.b64encode(b"UnityFS-fake").decode()}))
    return pack


def mono_yaml(guid: str) -> str:
    return f"  m_Script: {{fileID: 11500000, guid: {guid}, type: 3}}\n"


def test_alignment(tmp: Path, r: Result) -> None:
    print("\n=== 1. 脚本免挂对齐 ===")
    import sfs_pack_core as ka

    toolkit = make_toolkit(tmp)
    pack = make_pack(tmp)
    project = tmp / "Project"
    write(project / "Assets" / "Scripts" / "Part.cs", "public class Part {}\n")
    write(project / "Assets" / "Scripts" / "Part.cs.meta", unity_meta(STUB_IN_SCRIPTS))
    write(project / "Assets" / "MonoScript" / "Part.cs", "public class Part {}\n")
    write(project / "Assets" / "MonoScript" / "Part.cs.meta", unity_meta(STUB_IN_MONOSCRIPT))
    write(project / "Assets" / "Parts" / "Engine.prefab", mono_yaml(STUB_IN_SCRIPTS) + mono_yaml(STUB_IN_MONOSCRIPT))
    write(project / "Assets" / "Configs" / "Settings.asset", mono_yaml(STUB_IN_SCRIPTS))

    logs: list[str] = []
    rep = ka.align_scripts_to_toolkit(project, pack, toolkit, log=logs.append)
    for line in logs:
        print("   ", line)

    scripts = project / "Assets" / "Scripts"
    part_meta = (scripts / "Part.cs.meta").read_text(encoding="utf-8")
    prefab = (project / "Assets" / "Parts" / "Engine.prefab").read_text(encoding="utf-8")
    asset = (project / "Assets" / "Configs" / "Settings.asset").read_text(encoding="utf-8")

    r.check("stub 已删除，Part.cs 换成 Toolkit GUID", TOOLKIT_PART in part_meta)
    r.check("依赖闭包已整拷（Base.cs）", (scripts / "Base.cs").is_file())
    r.check("Assets/MonoScript 下的 stub 也被清理", not (project / "Assets" / "MonoScript" / "Part.cs").exists())
    r.check(".prefab 引用已重写", TOOLKIT_PART in prefab and STUB_IN_SCRIPTS not in prefab)
    r.check("第二处引用（另一 stub）也重写", STUB_IN_MONOSCRIPT not in prefab)
    r.check(".asset 引用已重写（ScriptableObject 覆盖）", TOOLKIT_PART in asset)
    r.check("未误报 unresolved", rep.get("unresolved_classes") == [])


def test_merge_and_dedupe(tmp: Path, r: Result) -> None:
    print("\n=== 2. 合并包 + 同名去重 ===")
    import sfs_pack_core as ka

    toolkit = make_toolkit(tmp)
    pack = make_pack(tmp)
    project = tmp / "Project2"
    for i, sub in enumerate(("A", "B")):
        write(project / "Assets" / sub / "Engine.prefab", mono_yaml(TOOLKIT_PART))
    write(project / "Assets" / "A" / "Other.prefab", mono_yaml(TOOLKIT_PART))

    logs: list[str] = []
    merge = tmp / "Merge2"
    mrep = ka.build_merge_package(project, pack, toolkit, merge, log=logs.append)
    for line in logs:
        print("   ", line)

    sub = str(mrep.get("parts_subfolder") or "")
    parts = merge / "Assets" / "Resources" / "Parts" / sub
    r.check("新增部件放进以模组命名的子目录", bool(sub) and mrep.get("ok", False) and (parts / "Engine.prefab").is_file())
    r.check("同名 prefab 已去重（只保留 1 个 Engine）", mrep.get("new_parts") == 2 and mrep.get("duplicate_parts"))
    r.check("合并包内不含 .cs", not any(merge.rglob("*.cs")))


def test_stub_shader_fix(tmp: Path, r: Result) -> None:
    print("\n=== 2b. 空壳着色器（黑板）自动修复 ===")
    import sfs_pack_core as ka

    toolkit = make_toolkit(tmp / "tk_shader")
    # Toolkit 真着色器：Additive.shader 里声明 Shader "SFS/Weird"
    tk_shader = toolkit / "Assets" / "Materials" / "Shaders" / "Additive.shader"
    write(tk_shader, 'Shader "SFS/Weird" {\n SubShader { Pass { Blend One OneMinusSrcColor } }\n}\n')
    write(Path(str(tk_shader) + ".meta"), unity_meta("a" * 32))

    project = tmp / "ProjectShader"
    stub = project / "Assets" / "Shader" / "SFS_Weird.shader"
    write(stub, '//DummyShaderTextExporter\nShader "SFS/Weird" {\n SubShader { Pass { } }\n}\n')
    write(Path(str(stub) + ".meta"), unity_meta("b" * 32))
    write(project / "Assets" / "Parts" / "Glow.mat", "%YAML 1.1\n  m_Shader: {fileID: 4800000, guid: " + "b" * 32 + ", type: 3}\n")

    logs: list[str] = []
    rep = ka.fix_stub_shaders(project / "Assets", toolkit, log=logs.append, mode="copy")
    for line in logs:
        print("   ", line)
    r.check("copy 模式检出空壳", rep["stubs"] == 1)
    r.check("copy 模式换成真源码且保留 GUID", "Blend One OneMinusSrcColor" in stub.read_text(encoding="utf-8"))
    r.check("copy 模式不改材质", ("guid: " + "b" * 32) in (project / "Assets" / "Parts" / "Glow.mat").read_text(encoding="utf-8"))

    logs2: list[str] = []
    rep2 = ka.fix_stub_shaders(project / "Assets", toolkit, log=logs2.append, mode="remap")
    for line in logs2:
        print("   ", line)
    r.check("remap 模式重写材质到 Toolkit GUID", rep2["refs"] == 1 and ("guid: " + "a" * 32) in (project / "Assets" / "Parts" / "Glow.mat").read_text(encoding="utf-8"))
    r.check("remap 模式删掉重复着色器", not stub.exists() and rep2["deleted"] == 2)
    r.check("remap 幂等（再跑一次无空壳）", ka.fix_stub_shaders(project / "Assets", toolkit, log=lambda *_: None, mode="remap")["stubs"] == 0)


def test_toolkit_duplicate_remap(tmp: Path, r: Result) -> None:
    print("\n=== 2d. 原版资源按相对路径对齐到 Toolkit ===")
    import sfs_pack_core as ka

    toolkit = make_toolkit(tmp / "tk_dup")
    tk_assets = toolkit / "Assets"
    g_tk_mat, g_tk_tex = "1" * 32, "2" * 32
    g_exp_mat, g_exp_tex, g_exp_custom = "3" * 32, "4" * 32, "6" * 32

    # Toolkit 自带的原版材质 / 贴图
    write(tk_assets / "Material" / "Weird.mat",
          "Material:\n  m_Shader: {fileID: 4800000, guid: %s, type: 3}\n"
          "  m_Tex: {fileID: 2800000, guid: %s, type: 3}\n" % ("e" * 32, g_tk_tex))
    write(tk_assets / "Material" / "Weird.mat.meta", unity_meta(g_tk_mat))
    write(tk_assets / "Texture2D" / "T.png", "PNGDATA")
    write(tk_assets / "Texture2D" / "T.png.meta", unity_meta(g_tk_tex))
    # 同名但 Toolkit 版本内容不同的一份
    write(tk_assets / "Material" / "Custom.mat", "Material:\n  m_Name: TK\n")
    write(tk_assets / "Material" / "Custom.mat.meta", unity_meta("5" * 32))

    pack = make_pack(tmp / "dup.pack")
    project = tmp / "ProjectDup"
    pa = project / "Assets"
    # 导出工程：同一份材质/贴图的「平行 GUID 副本」，结构一致、仅 guid 不同
    write(pa / "Material" / "Weird.mat",
          "Material:\n  m_Shader: {fileID: 4800000, guid: %s, type: 3}\n"
          "  m_Tex: {fileID: 2800000, guid: %s, type: 3}\n" % ("f" * 32, g_exp_tex))
    write(pa / "Material" / "Weird.mat.meta", unity_meta(g_exp_mat))
    write(pa / "Texture2D" / "T.png", "PNGDATA")
    write(pa / "Texture2D" / "T.png.meta", unity_meta(g_exp_tex))
    # 同名但内容确有差异
    write(pa / "Material" / "Custom.mat", "Material:\n  m_Name: MOD CHANGED\n")
    write(pa / "Material" / "Custom.mat.meta", unity_meta(g_exp_custom))
    # 新部件同时引用平行世界的两份材质
    write(pa / "Gadget.prefab",
          mono_yaml(TOOLKIT_PART)
          + "  m_Materials:\n"
          + "  - {fileID: 2100000, guid: %s, type: 2}\n" % g_exp_mat
          + "  - {fileID: 2100000, guid: %s, type: 2}\n" % g_exp_custom)

    merge = tmp / "MergeDup"
    mrep = ka.build_merge_package(project, pack, toolkit, merge, log=lambda *_: None)
    r.check("合并成功", mrep.get("ok", False))
    r.check("识别出 3 个同名资源", mrep.get("dup_redirected", 0) + len(mrep.get("dup_kept_diff") or []) == 3)
    r.check("等价副本被重定向（Weird.mat / T.png 共 2 个）", mrep.get("dup_redirected") == 2)

    sub = str(mrep.get("parts_subfolder") or "")
    pf = (merge / "Assets" / "Resources" / "Parts" / sub / "Gadget.prefab").read_text(encoding="utf-8")
    r.check("prefab 材质引用改指 Toolkit 的 Weird.mat", g_tk_mat in pf and g_exp_mat not in pf)
    r.check("重复副本已从包里移除",
            not (merge / "Assets" / "Material" / "Weird.mat").exists()
            and not (merge / "Assets" / "Texture2D" / "T.png").exists())
    kept = list((merge / "Assets").rglob("*Custom*.mat"))
    r.check("内容不同的同名资源保留并改名", len(kept) == 1 and kept[0].name.startswith(sub + "_"))
    r.check("保留的那份 GUID 未变（引用照旧有效）",
            g_exp_custom in Path(str(kept[0]) + ".meta").read_text(encoding="utf-8"))
    r.check("保留的那份仍被 prefab 引用", g_exp_custom in pf)


def test_remap_by_name(tmp: Path, r: Result) -> None:
    """2h. 同名不同路径的原版材质也能被重定向（防火焰材质悬空）。"""
    import sfs_pack_core as ka

    print("\n=== 2h. 同名不同路径材质按名字对齐（防火焰悬空） ===")
    toolkit = make_toolkit(tmp / "tk_name")
    tk_assets = toolkit / "Assets"
    g_tk = "a" * 32
    # Toolkit 真材质在 Material/ 下
    write(tk_assets / "Material" / "Flame.mat", "Material:\n  m_Name: Flame\n")
    write(tk_assets / "Material" / "Flame.mat.meta", unity_meta(g_tk))

    pack = make_pack(tmp / "name.pack")
    project = tmp / "ProjectName"
    pa = project / "Assets"
    g_exp = "b" * 32
    # 包里同名材质但在不同子目录 Materials/（模拟 mod 把原版材质放别处）
    write(pa / "Materials" / "Flame.mat", "Material:\n  m_Name: Flame\n")
    write(pa / "Materials" / "Flame.mat.meta", unity_meta(g_exp))
    # 一个部件引用包里这份材质的 GUID
    write(pa / "Glow.prefab",
          "MeshRenderer:\n  m_Materials:\n  - {fileID: 2100000, guid: %s, type: 2}\n" % g_exp)

    merge = tmp / "MergeName"
    mrep = ka.build_merge_package(project, pack, toolkit, merge, log=lambda *_: None)
    r.check("包内检测到同名资源（按名字）", mrep.get("dup_redirected", 0) >= 1)
    sub = str(mrep.get("parts_subfolder") or "")
    pf = (merge / "Assets" / "Resources" / "Parts" / sub / "Glow.prefab").read_text(encoding="utf-8")
    r.check("同名不同路径材质被重定向到 Toolkit GUID", g_tk in pf and g_exp not in pf)
    r.check("包内重复材质副本已移除（不再悬空）", not (merge / "Assets" / "Materials" / "Flame.mat").exists())


def test_repair_dangling_selfheal(tmp: Path, r: Result) -> None:
    """2i. 修复 Toolkit 按钮的悬空引用自愈扫描（提供/不提供原始 mod 工程两种路径）。"""
    import sfs_pack_core as ka
    print("\n=== 2i. 修复 Toolkit：悬空引用自愈扫描 ===")
    noop = lambda *a, **k: None

    # ---- 场景 A：提供原始 mod 工程，Toolkit 已有同名等价材质 -> 重定向 ----
    tkA = make_toolkit(tmp / "tk_dangA")
    tkA_assets = tkA / "Assets"
    g_tk, g_bad = "a1" * 16, "b9" * 16
    write(tkA_assets / "Material" / "Weird.mat", "Material:\n  m_Name: Weird\n")
    write(tkA_assets / "Material" / "Weird.mat.meta", unity_meta(g_tk))
    write(tkA_assets / "Resources" / "Parts" / "Mod" / "Gadget.prefab",
          "  m_Materials:\n  - {fileID: 2100000, guid: %s, type: 2}\n" % g_bad)
    write(tkA_assets / "Resources" / "Parts" / "Mod" / "Gadget.prefab.meta", unity_meta("c" * 32))
    pkgA = tmp / "PkgDangA"
    write(pkgA / "Assets" / "Materials" / "Weird.mat", "Material:\n  m_Name: Weird\n")  # 与 Toolkit 等价
    write(pkgA / "Assets" / "Materials" / "Weird.mat.meta", unity_meta(g_bad))

    repA = ka.repair_toolkit_dangling_refs(tkA, package_assets=pkgA, log=noop, backup=False)
    r.check("A: 扫到 1 处悬空", repA.get("dangling") == 1)
    r.check("A: 按同名重定向 1 处", repA.get("redirected") == 1)
    r.check("A: 未补入资产", repA.get("imported") == 0)
    r.check("A: 无未解决", repA.get("unresolved") == 0)
    pfA = (tkA_assets / "Resources" / "Parts" / "Mod" / "Gadget.prefab").read_text(encoding="utf-8")
    r.check("A: prefab 引用改指 Toolkit 的 Weird.mat", g_tk in pfA and g_bad not in pfA)

    # ---- 场景 B：Toolkit 缺同名材质 -> 补入原版(保留原 GUID) ----
    tkB = make_toolkit(tmp / "tk_dangB")
    tkB_assets = tkB / "Assets"
    g_badB = "d4" * 16
    write(tkB_assets / "Resources" / "Parts" / "Mod" / "Glow.prefab",
          "  m_Materials:\n  - {fileID: 2100000, guid: %s, type: 2}\n" % g_badB)
    write(tkB_assets / "Resources" / "Parts" / "Mod" / "Glow.prefab.meta", unity_meta("e" * 32))
    pkgB = tmp / "PkgDangB"
    write(pkgB / "Assets" / "Materials" / "Flame.mat", "Material:\n  m_Name: Flame\n")
    write(pkgB / "Assets" / "Materials" / "Flame.mat.meta", unity_meta(g_badB))

    repB = ka.repair_toolkit_dangling_refs(tkB, package_assets=pkgB, log=noop, backup=False)
    r.check("B: 扫到 1 处悬空", repB.get("dangling") == 1)
    r.check("B: 补入 1 个缺失资产", repB.get("imported") == 1)
    r.check("B: 无重定向", repB.get("redirected") == 0)
    r.check("B: 无未解决", repB.get("unresolved") == 0)
    imported = list((tkB_assets).rglob("Flame.mat"))
    r.check("B: 原版材质已补入 Toolkit", len(imported) == 1)
    r.check("B: 补入材质保留原 GUID(引用自然通)",
            g_badB in Path(str(imported[0]) + ".meta").read_text(encoding="utf-8"))

    # ---- 场景 C：不提供原始 mod 工程 -> 仅扫描+清单，绝不误改 ----
    tkC = make_toolkit(tmp / "tk_dangC")
    tkC_assets = tkC / "Assets"
    g_badC = "f7" * 16
    write(tkC_assets / "Resources" / "Parts" / "Mod" / "X.prefab",
          "  m_Materials:\n  - {fileID: 2100000, guid: %s, type: 2}\n" % g_badC)
    write(tkC_assets / "Resources" / "Parts" / "Mod" / "X.prefab.meta", unity_meta("9" * 32))
    repC = ka.repair_toolkit_dangling_refs(tkC, package_assets=None, log=noop, backup=False)
    r.check("C: 扫到 1 处悬空", repC.get("dangling") == 1)
    r.check("C: 未提供包 -> 不重定向不补入", repC.get("redirected") == 0 and repC.get("imported") == 0)
    r.check("C: 全部转为未解决清单", repC.get("unresolved") == 1)
    r.check("C: 生成清单文件", bool(repC.get("manifest")) and Path(str(repC.get("manifest"))).is_file())
    pfC = (tkC_assets / "Resources" / "Parts" / "Mod" / "X.prefab").read_text(encoding="utf-8")
    r.check("C: 引用未被误改", g_badC in pfC)


def test_install_repairs_dangling(tmp: Path, r: Result) -> None:
    print("\n=== 4b. 并入时修复引用悬空的既有资产 ===")
    spec = importlib.util.spec_from_file_location("gui_repair", BUILD_KIT / "sfs_pack_tool_gui.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    toolkit = make_toolkit(tmp / "tk_repair")
    tk_assets = toolkit / "Assets"
    g_tex, g_bad, g_part = "7" * 32, "9" * 32, "8" * 32
    write(tk_assets / "Texture2D" / "Real.png", "PNG")
    write(tk_assets / "Texture2D" / "Real.png.meta", unity_meta(g_tex))
    # Toolkit 里已有一份坏 prefab：引用了 Toolkit 里根本不存在的 guid
    bad_dir = tk_assets / "Resources" / "Parts" / "Mod A"
    write(bad_dir / "Gadget.prefab", "  m_Materials:\n  - {fileID: 2100000, guid: %s, type: 2}\n" % g_bad)
    write(bad_dir / "Gadget.prefab.meta", unity_meta(g_part))
    # 内容正常的一份，不该被动
    write(bad_dir / "Good.prefab", "  m_Materials:\n  - {fileID: 2100000, guid: %s, type: 2}\n" % g_tex)
    write(bad_dir / "Good.prefab.meta", unity_meta("a" * 32))

    pkg = tmp / "PkgRepair"
    write(pkg / "Assets" / "Resources" / "Parts" / "Mod A" / "Gadget.prefab",
          "  m_Materials:\n  - {fileID: 2100000, guid: %s, type: 2}\n" % g_tex)
    write(pkg / "Assets" / "Resources" / "Parts" / "Mod A" / "Gadget.prefab.meta", unity_meta(g_part))
    write(pkg / "Assets" / "Resources" / "Parts" / "Mod A" / "Good.prefab",
          "  m_Materials:\n  - {fileID: 2100000, guid: %s, type: 2}\n" % g_bad)
    write(pkg / "Assets" / "Resources" / "Parts" / "Mod A" / "Good.prefab.meta", unity_meta("a" * 32))

    class _Shell:
        t = staticmethod(lambda key, **kw: key)

    logs: list[str] = []
    module.App.install_into_toolkit(_Shell(), logs.append, toolkit, pkg, {"ok": True})

    fixed = (bad_dir / "Gadget.prefab").read_text(encoding="utf-8")
    r.check("悬空 prefab 已被修复覆盖", g_tex in fixed and g_bad not in fixed)
    intact = (bad_dir / "Good.prefab").read_text(encoding="utf-8")
    r.check("原本正常的资产不被覆盖（悬空数没下降）", g_tex in intact and g_bad not in intact)
    backups = [p for p in toolkit.rglob("Gadget.prefab") if "_PackToolBackup" in str(p)]
    r.check("被覆盖的原文件已备份", len(backups) == 1)
    r.check("报告了修复数量", any("install_repair_done" in x for x in logs))


def test_pack_info_and_strip_guards(tmp: Path, r: Result) -> None:
    print("\n=== 2c. 包信息部件数 / 剥离兜底 ===")
    spec = importlib.util.spec_from_file_location("gui_info", BUILD_KIT / "sfs_pack_tool_gui.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    def obj(name, pid, father=None, go=None):
        class _O:
            type = type("T", (), {"name": name})()
            path_id = pid

            def read_typetree(self):
                if father is None:
                    raise RuntimeError("no typetree")
                return {
                    "m_Father": {"m_FileID": 0, "m_PathID": father},
                    "m_GameObject": {"m_FileID": 0, "m_PathID": go},
                }
        return _O()

    # 2 个部件：各有一个根 Transform + 一个子 Transform；另有 6 个 MonoBehaviour
    objs = [
        obj("Transform", 10, father=0, go=1),
        obj("Transform", 11, father=10, go=2),
        obj("Transform", 20, father=0, go=3),
        obj("Transform", 21, father=20, go=4),
    ] + [obj("MonoBehaviour", 100 + i) for i in range(6)] + [obj("GameObject", 1), obj("GameObject", 3)]

    class _Env:
        def __init__(self, o):
            self.objects = o

    class _FakeUnityPy:
        @staticmethod
        def load(_payload):
            return _Env(objs)

    module.UnityPy = _FakeUnityPy
    count = module.count_bundle_parts(b"fake")
    r.check("部件数按 prefab 根统计=2（不被 MonoBehaviour 撑大）", count == 2)

    # 直接把 i18n key 当文案输出，断言只看 key，不受措辞改动影响
    translate = lambda key, **kw: key  # noqa: E731
    src = tmp / "guard.pack"
    write(src, json.dumps({"AndroidBuild": "AAAA"}))
    logs: list[str] = []
    module.strip_pack(str(src), str(tmp / "out.pack"), "WindowsBuild", translate, logs.append)
    r.check("目标平台不在包里时拒绝剥离", any("strip_no_target" in x for x in logs))

    logs2: list[str] = []
    module.strip_pack(str(src), str(src), "AndroidBuild", translate, logs2.append)
    r.check("拒绝把剥离结果写回源 .pack", any("strip_output_is_input" in x for x in logs2))
    r.check("源 .pack 未被改写", json.loads(src.read_text(encoding="utf-8")) == {"AndroidBuild": "AAAA"})

    logs3: list[str] = []
    out3 = tmp / "ok.pack"
    module.strip_pack(str(src), str(out3), "AndroidBuild", translate, logs3.append)
    r.check("正常平台可以剥离", out3.is_file() and json.loads(out3.read_text(encoding="utf-8")) == {"AndroidBuild": "AAAA"})

    logs4: list[str] = []
    module.analyze_pack(str(src), translate, logs4.append)
    r.check("无 CodeAssembly 时如实显示未包含", any("assembly_absent" in x for x in logs4))


def test_toolkit_selfcheck(tmp: Path, r: Result) -> None:
    print("\n=== 3. Toolkit 前提自检 ===")
    import sfs_pack_core as ka

    good = make_toolkit(tmp / "good")
    write(good / "Assets" / "Resources" / "Parts" / "Stock.prefab", mono_yaml(TOOLKIT_PART))
    ok = ka.verify_toolkit_self(good)
    print("    good:", ok)
    r.check("同版本 Toolkit 自检 0 缺失", ok["missing"] == 0 and ok["refs"] == 1)

    bad = make_toolkit(tmp / "bad")
    write(bad / "Assets" / "Scripts" / "Part.cs.meta", unity_meta("9" * 32))  # 模拟 meta 被重新生成
    write(bad / "Assets" / "Resources" / "Parts" / "Stock.prefab", mono_yaml(TOOLKIT_PART))
    ng = ka.verify_toolkit_self(bad)
    print("    bad :", ng)
    r.check("GUID 不符时自检能报出缺失", ng["missing"] == 1)


def test_install_never_overwrites(tmp: Path, r: Result) -> None:
    print("\n=== 4. 并入 Toolkit 不覆盖既有文件 ===")
    spec = importlib.util.spec_from_file_location("gui_app", BUILD_KIT / "sfs_pack_tool_gui.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    class _Shell:  # 只需要 install_into_toolkit 用到的 self.t()
        t = staticmethod(lambda key, **kw: f"{key}:{kw}")

    toolkit = tmp / "Toolkit3"
    write(toolkit / "Assets" / "Textures" / "metal.png.meta", unity_meta("1" * 32))
    write(toolkit / "Assets" / "Textures" / "metal.png", "ORIGINAL")  # 用户既有内容
    package = tmp / "Pkg3"
    write(package / "Assets" / "Textures" / "metal.png", "FROM_MOD")
    write(package / "Assets" / "Textures" / "metal.png.meta", unity_meta("1" * 32))
    write(package / "Assets" / "Resources" / "Parts" / "New.prefab", mono_yaml("2" * 32))

    logs: list[str] = []
    module.App.install_into_toolkit(_Shell(), logs.append, toolkit, package, {"new_parts": 1})
    for line in logs:
        print("   ", line)

    r.check("既有文件未被覆盖", (toolkit / "Assets" / "Textures" / "metal.png").read_text() == "ORIGINAL")
    r.check("新文件已写入", (toolkit / "Assets" / "Resources" / "Parts" / "New.prefab").is_file())
    r.check("提示了跳过数量", any("install_skipped" in line for line in logs))


def test_install_replaces_stale_guid(tmp: Path, r: Result) -> None:
    """贴图挂空的根因回归：Toolkit 里同名文件占着**旧 GUID**，而 prefab 引用的是新 GUID。

    合并包里那份是对的（GUID 与新 prefab 一致），但 install 原来一律"已存在就跳过"，
    于是磁盘上永远躺着旧版本 → 贴图/材质一直挂空。现在必须替换（并备份）。
    """
    print("\n=== 4c. 并入时替换 GUID 过期的同名残留（贴图挂空根因）===")
    spec = importlib.util.spec_from_file_location("gui_stale", BUILD_KIT / "sfs_pack_tool_gui.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    class _Shell:
        t = staticmethod(lambda key, **kw: f"{key}:{kw}")

    NEW, OLD = "1" * 32, "2" * 32
    toolkit = tmp / "ToolkitStale"
    tk_other = toolkit / "Assets" / "Mod A" / "Other"
    # Toolkit 里是上一轮导入留下的旧版本：同名、GUID=OLD
    write(tk_other / "Color_White_0.asset", "OLD_CONTENT")
    write(tk_other / "Color_White_0.asset.meta", unity_meta(OLD))
    # 另一个同名文件，包内那份的 GUID 也没人引用 → 不该动它
    write(tk_other / "Keep.asset", "KEEP_ORIGINAL")
    write(tk_other / "Keep.asset.meta", unity_meta("3" * 32))

    package = tmp / "PkgStale"
    pkg_other = package / "Assets" / "Mod A" / "Other"
    write(pkg_other / "Color_White_0.asset", "NEW_CONTENT")
    write(pkg_other / "Color_White_0.asset.meta", unity_meta(NEW))
    write(pkg_other / "Keep.asset", "KEEP_FROM_PKG")
    write(pkg_other / "Keep.asset.meta", unity_meta("4" * 32))
    # 包内 prefab 引用 NEW —— 这正是本次导入真正需要的 GUID
    write(package / "Assets" / "Resources" / "Parts" / "Mod A" / "P.prefab",
          "  colorTexture: {fileID: 11400000, guid: %s, type: 2}\n" % NEW)

    logs: list[str] = []
    module.App.install_into_toolkit(_Shell(), logs.append, toolkit, package, {"ok": True})
    for line in logs:
        print("   ", line)

    r.check("过期 GUID 的同名残留已被替换",
            (tk_other / "Color_White_0.asset").read_text(encoding="utf-8") == "NEW_CONTENT")
    r.check("对应 .meta 的 GUID 已换成新的",
            NEW in (tk_other / "Color_White_0.asset.meta").read_text(encoding="utf-8"))
    r.check("旧 GUID 已不在",
            OLD not in (tk_other / "Color_White_0.asset.meta").read_text(encoding="utf-8"))
    backups = [p for p in toolkit.rglob("Color_White_0.asset") if "_PackToolBackup" in str(p)]
    r.check("被替换的原文件已备份", len(backups) == 1)
    r.check("包内 GUID 未被引用的同名文件不受影响",
            (tk_other / "Keep.asset").read_text(encoding="utf-8") == "KEEP_ORIGINAL")
    r.check("报告了替换数量", any("install_replaced_stale" in x for x in logs))


def test_merge_keeps_mod_dll(tmp: Path, r: Result) -> None:
    print("\n=== 5. 合并包必须携带 mod 自有程序集(DLL) ===")
    import sfs_pack_core as ka

    toolkit = make_toolkit(tmp)
    pack = make_pack(tmp)
    project = tmp / "Project5"
    # mod 自有程序集：AssetRipper 放进 Plugins，prefab 的 m_Script 直接指向它的 guid
    (project / "Assets" / "Plugins").mkdir(parents=True, exist_ok=True)
    (project / "Assets" / "Plugins" / "AssetsofIce.dll").write_bytes(b"MZ-fake-assembly-bytes")
    write(project / "Assets" / "Plugins" / "AssetsofIce.dll.meta", unity_meta(MOD_DLL_GUID))
    # 一个引用该 DLL 的部件（同时引用一个 Toolkit 类，模拟混合引用）
    write(project / "Assets" / "Parts" / "Reactor.prefab",
          mono_yaml(MOD_DLL_GUID) + mono_yaml(TOOLKIT_PART))

    logs: list[str] = []
    merge = tmp / "Merge5"
    mrep = ka.build_merge_package(project, pack, toolkit, merge, log=logs.append)
    for line in logs:
        print("   ", line)

    dll_out = merge / "Assets" / "Plugins" / "AssetsofIce.dll"
    meta_out = merge / "Assets" / "Plugins" / "AssetsofIce.dll.meta"
    r.check("合并包含 mod DLL", dll_out.is_file())
    r.check("合并包含 DLL 的 .meta(guid 一致)", meta_out.is_file()
            and MOD_DLL_GUID in meta_out.read_text(encoding="utf-8"))
    r.check("报告里记录了携带的 DLL 数", mrep.get("mod_custom_dll", 0) == 1)
    r.check("DLL 不被 MERGE_SKIP_SUFFIXES 误删", mrep.get("ok", False))


def test_stub_bom_and_toolkit_repair(tmp: Path, r: Result) -> None:
    """2e. BOM 真身识别 + 真身优先 + m_Name 同步 + 直接清理 Toolkit 内残留空壳。"""
    import sfs_pack_core as ka

    print("\n=== 2e. 空壳着色器：BOM 真身 / 真身优先 / m_Name 同步 / Toolkit 自清理 ===")
    toolkit = make_toolkit(tmp / "tk_bom")
    tk_assets = toolkit / "Assets"

    # 真身材质：Materials/Shaders/SpriteWithDepth.shader 带 UTF-8 BOM 且声明 SFS/Sprite With Depth
    real_shader = tk_assets / "Materials" / "Shaders" / "SpriteWithDepth.shader"
    write(real_shader, "\ufeffShader \"SFS/Sprite With Depth\" {\n SubShader { Pass { Blend SrcAlpha One } } }\n")
    write(Path(str(real_shader) + ".meta"), unity_meta("c0ffee" + "0" * 26))

    # 同名空壳：Shader/SFS_Sprite With Depth.shader（带 DummyShaderTextExporter，不同 guid）
    stub = tk_assets / "Shader" / "SFS_Sprite With Depth.shader"
    write(stub, "//DummyShaderTextExporter\nShader \"SFS/Sprite With Depth\" {\n SubShader { Pass { } } }\n")
    write(Path(str(stub) + ".meta"), unity_meta("d0" + "0" * 30))

    # 一个引用空壳 guid 的材质（内部 m_Name 与文件名不一致，触发 Odin 警告）
    mat = tk_assets / "Material" / "Engine Olders 1v_Sprite Depth.mat"
    write(mat, "Material:\n  m_Shader: {fileID: 4800000, guid: %s, type: 3}\n" % ("d0" + "0" * 30))
    write(Path(str(mat) + ".meta"), unity_meta("d1" + "0" * 30))
    # 故意把内部名字写成旧的，制造名字不匹配
    mat_text = mat.read_text(encoding="utf-8").replace("Material:", "Material:\n  m_Name: Sprite Depth")
    mat.write_text(mat_text, encoding="utf-8")

    # 直接清理 Toolkit 内残留空壳（用户的真实场景）
    rep = ka.repair_toolkit_shaders(toolkit, log=lambda *_: None, backup=False)
    r.check("Toolkit 自清理检出 1 个空壳", rep["stubs"] == 1)
    r.check("空壳被删除", not stub.exists())
    r.check("材质引用已重指向真身 GUID", ("guid: c0ffee" + "0" * 26) in mat.read_text(encoding="utf-8"))
    r.check("m_Name 已同步为文件名(消掉 Odin 警告)",
            "m_Name: Engine Olders 1v_Sprite Depth" in mat.read_text(encoding="utf-8"))

    # 幂等：再跑一次无空壳
    rep2 = ka.repair_toolkit_shaders(toolkit, log=lambda *_: None, backup=False)
    r.check("Toolkit 自清理幂等（无空壳）", rep2["stubs"] == 0)


def test_export_button_wires_run_async(r: Result) -> None:
    """2f. 静态守护：start_export 必须真正调用 run_async 启动导出。

    历史上一次编辑把 _run 闭包和 self.run_async(_run) 整段删掉，导致点「导出」
    只把按钮置成“导出中”就返回，没有任何日志、导出永远卡住。用 ast 解析源码
    （不触发 tkinter 导入）确认 start_export 内部存在 self.run_async(...) 调用。
    """
    import ast

    print("\n=== 2f. 导出按钮必须接线 run_async（防回归） ===")
    src = (BUILD_KIT / "sfs_pack_tool_gui.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    def find_method(name: str):
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        return None

    fn = find_method("start_export")
    r.check("start_export 方法存在", fn is not None)
    if fn is None:
        return
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
    has_run_async = any(
        isinstance(c.func, ast.Attribute) and c.func.attr == "run_async"
        for c in calls
    )
    r.check("start_export 内调用了 self.run_async（否则导出会卡死且无日志）", has_run_async)


def test_sync_asset_name_indent(tmp: Path, r: Result) -> None:
    """2g. sync_asset_name 必须保留/补回 YAML 缩进（防顶格 m_Name 把材质损坏）。

    历史上一次 fix_asset_name_mismatches 把 m_Name 写成顶格，Unity 读不到
    主对象名 → 材质损坏 → Odin "Material {} has a missing shader" +
    RenderSortingModule.SetDepth NRE。回归测试覆盖四种情况。
    """
    import re

    import sfs_pack_core as ka

    print("\n=== 2g. sync_asset_name 保留 YAML 缩进（防顶格损坏） ===")
    assets = tmp / "AssetsIndent"
    assets.mkdir(parents=True, exist_ok=True)

    def top_level_mname(t: str) -> bool:
        # 是否存在列 0（顶格）的 m_Name
        return bool(re.search(r"(?m)^m_Name:", t))

    # 情况 1：顶格 m_Name（被历史 bug 写坏的那种）
    name_top = assets / "Engine Olders 1v_Weird.mat"
    body = (
        "%YAML 1.1\n"
        "%TAG !u! tag:unity3d.com,2011:\n"
        "--- !u!21 &2100000\n"
        "Material:\n"
        "  m_ObjectHideFlags: 0\n"
        "  m_CorrespondingSourceObject: {fileID: 0}\n"
        "m_Name: Weird\n"          # 顶格！
        "  m_Shader: {fileID: 4800000, guid: " + "e" * 32 + ", type: 3}\n"
    )
    write(name_top, body)
    changed = ka.sync_asset_name(name_top)
    txt = name_top.read_text(encoding="utf-8")
    r.check("顶格 m_Name 被判定需要修", changed is True)
    r.check("顶格 m_Name 已补回两空格缩进",
            "\n  m_Name: Engine Olders 1v_Weird\n" in txt)
    r.check("顶格 m_Name 不再顶格（无列0 m_Name）", not top_level_mname(txt))

    # 情况 2：缩进正常但名字不对
    name_wrong = assets / "Engine Olders 1v_Sprite Depth.mat"
    body2 = (
        "Material:\n"
        "  m_Shader: {fileID: 4800000, guid: " + "f" * 32 + ", type: 3}\n"
        "  m_Name: Sprite Depth\n"     # 缩进正确但名字旧
    )
    write(name_wrong, body2)
    ka.sync_asset_name(name_wrong)
    txt2 = name_wrong.read_text(encoding="utf-8")
    r.check("名字错的已对齐文件名",
            "  m_Name: Engine Olders 1v_Sprite Depth" in txt2)
    r.check("名字错的缩进保持不变（仍两空格）",
            "\n  m_Name:" in txt2 and not top_level_mname(txt2))

    # 情况 3：缩进正确且名字已对 → 不动
    name_ok = assets / "Correct.mat"
    body3 = "Material:\n  m_Name: Correct\n"
    write(name_ok, body3)
    changed3 = ka.sync_asset_name(name_ok)
    r.check("已正确对齐的材质不再改动", changed3 is False)
    r.check("已正确对齐的内容未被改写",
            name_ok.read_text(encoding="utf-8") == body3)

    # 情况 4：多 m_Name（prefab 子物体）→ 不碰
    multi = assets / "Gadget.prefab"
    body4 = (
        "GameObject:\n  m_Name: Root\n"
        "Transform:\n  m_Name: Child\n"
    )
    write(multi, body4)
    changed4 = ka.sync_asset_name(multi)
    r.check("多 m_Name 文件被跳过（不误改）", changed4 is False)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sfs_smoke_"))
    r = Result()
    try:
        install_fake_unitypy(tmp / "stubmod", ["Part"])
        test_alignment(tmp, r)
        test_merge_and_dedupe(tmp, r)
        test_stub_shader_fix(tmp, r)
        test_toolkit_duplicate_remap(tmp, r)
        test_remap_by_name(tmp, r)
        test_repair_dangling_selfheal(tmp, r)
        test_stub_bom_and_toolkit_repair(tmp, r)
        test_export_button_wires_run_async(r)
        test_sync_asset_name_indent(tmp, r)
        test_pack_info_and_strip_guards(tmp, r)
        test_toolkit_selfcheck(tmp, r)
        test_merge_keeps_mod_dll(tmp, r)
        test_install_never_overwrites(tmp, r)
        test_install_repairs_dangling(tmp, r)
        test_install_replaces_stale_guid(tmp, r)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n" + ("ALL PASS" if r.ok else "SOME FAILED"))
    return 0 if r.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
