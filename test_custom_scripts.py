#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自定义脚本还原离线验证：pack 带 CodeAssembly 时的两条路线。

默认方案B（自定义脚本兼容的主路径）：真 dll 当托管插件落进 Assets/Plugins，
零改 prefab；反编译源码只放工程外的 ModCode_Reference 作参考，绝不进 Assets
（否则与 dll 同名类重复定义 -> CS0101）。
兜底方案A：dll 没被识别成插件时，退回反编译接回并复用 stub 的 GUID。

不依赖真实 ilspycmd —— 用假的「反编译产物目录」替换掉反编译步骤。
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "sfs_pack_core.py"

STUB = """using UnityEngine;

namespace AssetsofIce
{
	public class PowerModule : MonoBehaviour
	{
		/*
		Dummy class. This could have happened for several reasons:
		1. No dll files were provided to AssetRipper.
		*/
	}
}
"""

REAL = """using UnityEngine;

namespace AssetsofIce;

public class PowerModule : MonoBehaviour
{
	public float maxGeneration;

	public void Tick()
	{
		maxGeneration += 1f;
	}
}
"""

HELPER = """namespace AssetsofIce;

public class FuelManager
{
	public int count;
}
"""

TOOLKIT_SAME_NAME = """namespace SFS.Parts.Modules;

public class MassModule : MonoBehaviour
{
	public float mass;
}
"""


def load_module():
    spec = importlib.util.spec_from_file_location("keep_alive", SRC)
    module = importlib.util.module_from_spec(spec)
    sys.modules["keep_alive"] = module
    spec.loader.exec_module(module)
    return module


def write(path: Path, text: str, guid: str = ""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if guid:
        Path(str(path) + ".meta").write_text(
            f"fileFormatVersion: 2\nguid: {guid}\nMonoImporter:\n  externalObjects: {{}}\n",
            encoding="utf-8",
        )


def main() -> int:
    ka = load_module()
    temp = Path(tempfile.mkdtemp(prefix="sfs_custom_"))
    project = temp / "Export"

    stub_guid = "a" * 32
    write(
        project / "Assets/Scripts/Assembly-CSharp/AssetsofIce/PowerModule.cs",
        STUB,
        stub_guid,
    )

    decompiled = temp / "Decompiled"
    write(decompiled / "AssetsofIce/PowerModule.cs", REAL)
    write(decompiled / "AssetsofIce/FuelManager.cs", HELPER)
    # 与 Toolkit 同名 —— 必须跳过，否则 CS0101
    write(decompiled / "SFS.Parts.Modules/MassModule.cs", TOOLKIT_SAME_NAME)

    ok = 0
    fail = 0

    def check(label: str, cond: bool):
        nonlocal ok, fail
        print(f"  [{'OK ' if cond else 'FAIL'}] {label}")
        ok += bool(cond)
        fail += not cond

    # 用假的反编译产物替换掉需要 .NET 的那一步
    ka.extract_code_assembly = lambda pack, out: (
        out.parent.mkdir(parents=True, exist_ok=True),
        out.write_bytes(b"MZfake"),
        out,
    )[-1]
    ka.decompile_assembly = lambda dll, out, log: decompiled
    # 只有 PowerModule 是 mod 自带 dll 提供的；ControlModule 属原版类(m_AssemblyName=Assembly-CSharp)
    ka.custom_monoscript_classes = lambda pack: {"PowerModule"}

    # 原版类的 stub：必须保留。删了它 prefab 就指向不存在的 GUID → 原版脚本全挂
    stock_stub = project / "Assets/Scripts/Assembly-CSharp/ControlModule.cs"
    write(stock_stub, "/* Dummy class */\npublic class ControlModule { }\n", "b" * 32)

    logs: list[str] = []
    rep = ka.restore_custom_scripts(
        project, temp / "x.pack", {"MassModule"}, ["PowerModule", "ControlModule"], logs.append
    )
    for line in logs:
        print("    " + line)

    print("\n=== 1. 方案B（默认）：真 dll 当插件，零改 prefab ===")
    check("还原成功", rep["ok"] is True)
    check("走的是 dll 路线", rep.get("via") == "dll")
    check("记录了还原的类", rep["classes"] == ["PowerModule", "ControlModule"])
    check("原版类(Assembly-CSharp)的 stub 保留不动 —— 防原版脚本全挂", stock_stub.is_file())
    plugin = project / "Assets" / "Plugins" / "CodeAssembly.dll"
    check("dll 落在 Assets/Plugins/CodeAssembly.dll", plugin.is_file())
    check("dll 文件名保持原样(匹配 m_AssemblyName)", plugin.name == "CodeAssembly.dll")
    check("dll 带 .meta（GUID 立即可用）", Path(str(plugin) + ".meta").is_file())
    check("原 stub 已删除(防与 dll 撞类 CS0101)",
          not (project / "Assets/Scripts/Assembly-CSharp/AssetsofIce/PowerModule.cs").is_file())
    check("原 stub 的 .meta 也已删除",
          not (project / "Assets/Scripts/Assembly-CSharp/AssetsofIce/PowerModule.cs.meta").is_file())
    check("反编译源码只放工程外的参考目录(不进 Assets)",
          (project / "ModCode_Reference/AssetsofIce/PowerModule.cs").is_file())
    check("Assets 内没有 PowerModule 源码(避免与 dll 重复定义)",
          not list((project / "Assets").rglob("PowerModule.cs")))
    check("工程内无重复类型", not ka.find_duplicate_types(project / "Assets"))

    print("\n=== 2. 方案A 兜底：dll 未被识别成插件时退回反编译接回 ===")
    project2 = temp / "ExportA"
    write(project2 / "Assets/Scripts/Assembly-CSharp/AssetsofIce/PowerModule.cs", STUB, stub_guid)
    ka._find_mod_assembly_dll = lambda assets, dll: (None, "")  # 强制 dll 路线不可用
    logs2: list[str] = []
    rep_a = ka.restore_custom_scripts(
        project2, temp / "x.pack", {"MassModule"}, ["PowerModule"], logs2.append
    )
    for line in logs2:
        print("    " + line)
    mod = project2 / "Assets" / "Scripts" / ka.MOD_CODE_DIRNAME
    check("兜底还原成功", rep_a["ok"] is True)
    check("写进了 ModCode 目录", (mod / "AssetsofIce/PowerModule.cs").is_file())
    check("源码是反编译版本(不是 stub)",
          "maxGeneration" in (mod / "AssetsofIce/PowerModule.cs").read_text(encoding="utf-8"))
    meta = mod / "AssetsofIce/PowerModule.cs.meta"
    check("生成了 .meta", meta.is_file())
    check("复用了原 stub 的 GUID(prefab 引用不用改)", stub_guid in meta.read_text(encoding="utf-8"))
    check("原 stub 已删除",
          not (project2 / "Assets/Scripts/Assembly-CSharp/AssetsofIce/PowerModule.cs").is_file())
    check("辅助类一并拷入(否则 CS0246)", (mod / "AssetsofIce/FuelManager.cs").is_file())
    check("与 Toolkit 同名的类被跳过", not (mod / "SFS.Parts.Modules/MassModule.cs").is_file())
    m = ka.scan_script_meta(project2 / "Assets" / "Scripts")
    check("PowerModule 的 GUID 已指向新文件", m.get("PowerModule") == stub_guid)
    check("FuelManager 也被索引到", "FuelManager" in m)
    check("MassModule 不在工程里", "MassModule" not in m)
    check("兜底时撤回 dll(避免源码与 dll 同名类重复定义)",
          not (project2 / "Assets" / "Plugins" / "CodeAssembly.dll").exists())

    print("\n=== 5. 没有 CodeAssembly 时优雅降级 ===")
    ka.extract_code_assembly = lambda pack, out: None
    rep2 = ka.restore_custom_scripts(
        project, temp / "y.pack", {"MassModule"}, ["PowerModule"], lambda _m: None
    )
    check("标记为无程序集", rep2["reason"] == "no_code_assembly")
    check("未误报成功", rep2["ok"] is False)
    check("没有动任何文件", rep2["files"] == 0)

    print("\n=== 6. .pack 权威脚本映射（不依赖 AssetRipper stub）===")
    # 6a. PPtr/ComponentPair/dict 三种形态都要能取出 path_id
    class _P:
        m_PathID = 12345

    class _Pair:
        component = _P()

    check("PPtr 取 path_id", ka._pptr_path_id(_P()) == 12345)
    check("ComponentPair 取 path_id", ka._pptr_path_id(_Pair()) == 12345)
    check("dict 取 path_id", ka._pptr_path_id({"m_PathID": 7}) == 7)
    check("空引用取 0", ka._pptr_path_id(None) == 0)

    # 6b. YAML 解析：节点 / 单值 PPtr / PPtr 列表
    yml = (
        "%YAML 1.1\n"
        "--- !u!1 &100\n"
        "GameObject:\n"
        "  m_Name: Root\n"
        "  m_Component:\n"
        "  - component: {fileID: 400}\n"
        "  - component: {fileID: 500}\n"
        "--- !u!4 &400\n"
        "Transform:\n"
        "  m_GameObject: {fileID: 100}\n"
        "  m_Father: {fileID: 0}\n"
        "  m_Children:\n"
        "  - {fileID: 410}\n"
        "--- !u!114 &500\n"
        "MonoBehaviour:\n"
        "  m_Script: {fileID: 11500000, guid: abcd1234abcd1234abcd1234abcd1234, type: 3}\n"
    )
    ypath = temp / "T.prefab"
    ypath.write_text(yml, encoding="utf-8")
    nodes = ka._parse_prefab_yaml(ypath)
    check("YAML 拆出 3 个节点", len(nodes) == 3)
    check("YAML 取标量字段", ka._yaml_field(nodes, 100, "m_Name") == "Root")
    check("YAML 取单值 PPtr", ka._yaml_file_id(nodes, 400, "m_GameObject") == 100)
    check("YAML 取 PPtr 列表", ka._yaml_file_id_list(nodes, 100, "m_Component") == [400, 500])
    check("YAML 取子节点列表", ka._yaml_file_id_list(nodes, 400, "m_Children") == [410])

    # 6c. 闸门报告要能写出来且含 GUID 与类名
    hits = {"abcd1234abcd1234abcd1234abcd1234": {"class": "Part", "count": 9,
                                                 "files": ["Assets/A.prefab"]}}
    rpt = ka.write_unresolved_report(temp / "UNRESOLVED_SCRIPTS.md", hits)
    body = rpt.read_text(encoding="utf-8")
    check("闸门报告已生成", rpt.is_file())
    check("闸门报告含 GUID", "abcd1234abcd1234abcd1234abcd1234" in body)
    check("闸门报告含类名", "Part" in body)

    print(f"\n结果: {ok} 通过 {fail} 失败")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
