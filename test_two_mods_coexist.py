#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0-1 端到端验证：两个带自定义脚本的模组能否共存于同一 Toolkit。

不使用真实 AssetRipper（离线），而是直接构造两个「已导出并改名」的合并包，
验证安装层与冲突预检的完整判定链：

  模组A 安装 → 模组B 安装 → 两者共存
  模组B 用同一个内部名（改名失效）→ 仍被拦截
  模组A 重装（同字节）→ 放行并刷新 GUID

这条链正是「能不能导出两个含自定义脚本的模组 / 会不会冲突」的答案。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import sfs_pack_core as core  # noqa: E402
import sfs_assembly_rename as rename  # noqa: E402

OK = FAIL = 0


def check(label: str, cond: bool, detail: str = ""):
    global OK, FAIL
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}" + (f"  → {detail}" if detail and not cond else ""))
    OK += bool(cond)
    FAIL += not cond


def write(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_mod_pack(temp: Path, name: str, class_name: str) -> Path:
    """造一个带自定义类与自定义脚本的 .pack（无平台包，只测脚本线）。"""
    src = temp / f"{name}_src"
    write(src / "Mod.cs", f"namespace {name} {{ public class {class_name} {{ }} }}\n")
    # 用真实最小 PE 构造器（复用 test_multi_assembly 里的实现）
    sys.path.insert(0, str(ROOT))
    import test_multi_assembly as tma
    dll_bytes = tma._build_minimal_pe()
    pack = temp / f"{name}.pack"
    pack.write_text(json.dumps({
        "WindowsBuild": "",
        "CodeAssembly": __import__("base64").b64encode(dll_bytes).decode("ascii"),
    }), encoding="utf-8")
    return pack


def make_prefab(proj_assets: Path, name: str, dll_guid: str, sub: str = "TestMod") -> Path:
    """造一个引用 mod 插件 dll 的 prefab（模拟真实导出工程）。"""
    path = proj_assets / "Resources" / "Parts" / sub / f"{name}.prefab"
    write(path, (
        "%YAML 1.1\n"
        "%TAG !u! tag:unity3d.com,2011:\n"
        "--- !u!1 &100\n"
        "GameObject:\n"
        "  m_ObjectHideFlags: 0\n"
        "  m_Name: " + name + "\n"
        "  m_Component:\n"
        "  - component: {fileID: 400}\n"
        "--- !u!114 &400\n"
        "MonoBehaviour:\n"
        "  m_ObjectHideFlags: 0\n"
        "  m_Script: {fileID: 11500000, guid: " + dll_guid + ", type: 3}\n"
        "  m_Name: \n"
    ))
    return path


def main() -> int:
    temp = Path(tempfile.mkdtemp(prefix="sfs_e2e_"))

    # ---- 模拟一个 Toolkit 工程（含 Assets 骨架）----
    tk = temp / "Toolkit"
    for sub in ("Assets/Scripts", "Assets/Resources/Parts", "Assets/Plugins"):
        (tk / sub).mkdir(parents=True, exist_ok=True)

    print("=== 1. 模组A：导出工程 + 落位插件 ===")
    pack_a = make_mod_pack(temp, "ModA", "PowerModule")
    proj_a = temp / "ModA_export"
    (proj_a / "Assets").mkdir(parents=True)
    inst_a = core.install_code_assembly_as_plugin(proj_a, pack_a, None, lambda *_: None)
    check("A 安装成功", inst_a["ok"], str(inst_a))
    asm_a = inst_a["assembly"]
    check("A 内部名已改", asm_a.lower() != "codeassembly", asm_a)
    check("A 文件名 = 内部名", Path(inst_a["dll"]).name == f"{asm_a}.dll",
          Path(inst_a["dll"]).name)
    check("A 的 dll 内部名可读回", rename.read_assembly_name(inst_a["dll"]) == asm_a)
    prefab_a = make_prefab(proj_a / "Assets", "PartA", inst_a["guid"], "ModA")
    check("A 的 prefab 引用了插件 guid", prefab_a.is_file())

    print("\n=== 2. 模组B：同样的 CodeAssembly，内部名不同 ===")
    pack_b = make_mod_pack(temp, "ModB", "FuelManager")
    proj_b = temp / "ModB_export"
    (proj_b / "Assets").mkdir(parents=True)
    inst_b = core.install_code_assembly_as_plugin(proj_b, pack_b, None, lambda *_: None)
    check("B 安装成功", inst_b["ok"], str(inst_b))
    asm_b = inst_b["assembly"]
    check("B 内部名与 A 不同", asm_a != asm_b, f"{asm_a} vs {asm_b}")
    check("B 文件名 = 内部名", Path(inst_b["dll"]).name == f"{asm_b}.dll")
    prefab_b = make_prefab(proj_b / "Assets", "PartB", inst_b["guid"], "ModB")
    check("B 的 prefab 引用了插件 guid", prefab_b.is_file())

    print("\n=== 3. 把 A 的合并包并入 Toolkit ===")
    pkg_a = temp / "ModA_pkg"
    core._merge_copy_custom_scripts(
        proj_a / "Assets", [prefab_a], pkg_a / "Assets", lambda *_: None)
    check("合并包带上 A 的 dll",
          (pkg_a / "Assets" / "Plugins" / f"{asm_a}.dll").is_file(),
          str(list((pkg_a / "Assets").rglob("*.dll"))))
    conf_a = core.detect_assembly_conflicts(tk, pkg_a, "ModA")
    check("A 首次并入无冲突", conf_a == [], str(conf_a))

    # 模拟安装：拷进 Toolkit
    import shutil
    for f in (pkg_a / "Assets").rglob("*"):
        if f.is_file():
            dest = tk / "Assets" / f.relative_to(pkg_a / "Assets")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
    check("A 已进 Toolkit",
          (tk / "Assets" / "Plugins" / f"{asm_a}.dll").is_file())

    print("\n=== 4. 把 B 的合并包也并进**同一个** Toolkit（关键） ===")
    pkg_b = temp / "ModB_pkg"
    core._merge_copy_custom_scripts(
        proj_b / "Assets", [prefab_b], pkg_b / "Assets", lambda *_: None)
    conf_b = core.detect_assembly_conflicts(tk, pkg_b, "ModB")
    check("B 与 A 无冲突（可共存）", conf_b == [], str(conf_b))
    if conf_b:
        for c in conf_b:
            print(f"      冲突: {c}")

    for f in (pkg_b / "Assets").rglob("*"):
        if f.is_file():
            dest = tk / "Assets" / f.relative_to(pkg_b / "Assets")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)

    plugins = sorted((tk / "Assets" / "Plugins").glob("*.dll"))
    check("Toolkit 里有两个 dll", len(plugins) == 2, str([p.name for p in plugins]))
    asm_names = sorted(rename.read_assembly_name(p) for p in plugins)
    check("两个 dll 内部名互不相同", asm_names[0] != asm_names[1], str(asm_names))
    check("没有叫 CodeAssembly 的残留",
          all(n.lower() != "codeassembly" for n in asm_names), str(asm_names))

    print("\n=== 5. 反例：改名失效（内部名仍相同）→ 必须被拦截 ===")
    pkg_c = temp / "ModC_pkg"
    dll_c = temp / "ModC_plain" / "CodeAssembly.dll"
    dll_c.parent.mkdir(parents=True)
    import test_multi_assembly as tma
    # 与 A 同名内部名，但内容不同（模拟另一份 CodeAsm_xxxx 撞名）
    dll_c.write_bytes(tma._build_minimal_pe(asm_a, f"{asm_a}.dll") + b"\x01")
    (pkg_c / "Assets" / "Plugins").mkdir(parents=True)
    shutil.copy2(dll_c, pkg_c / "Assets" / "Plugins" / f"{asm_a}.dll")
    write(pkg_c / "Assets" / "Plugins" / f"{asm_a}.dll.meta",
          "fileFormatVersion: 2\nguid: " + "9" * 32 + "\n")
    conf_c = core.detect_assembly_conflicts(tk, pkg_c, "ModC")
    check("内部名撞车 → 被拦截", len(conf_c) == 1, str(conf_c))
    check("拦截信息点出内部名", conf_c and conf_c[0]["assembly"] == asm_a, str(conf_c))

    print("\n=== 6. 场景回归：同名模组重导（字节相同）→ 放行 ===")
    conf_repeat = core.detect_assembly_conflicts(tk, pkg_a, "ModA")
    check("重导 A 放行（刷新 GUID）", conf_repeat == [], str(conf_repeat))

    print("\n=== 7. 结论数据 ===")
    print(f"  A 内部名: {asm_a}")
    print(f"  B 内部名: {asm_b}")
    print(f"  Toolkit Plugins: {[p.name for p in plugins]}")
    print("  → 两个含自定义脚本的模组可共存于同一 Toolkit")

    print(f"\n结果: {OK} 通过 {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
