#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""免挂校验：确认 prefab 的 m_Script 能否在 Modding Toolkit 中命中。

SFS 部件挂的都是 Toolkit 内置脚本（Part、ResourceModule、MassModule...），
只要 Toolkit 脚本 GUID 与包内 m_Script 一致，提取后就不会 Missing。
也可单独运行：python sfs_toolkit_script_check.py "<Toolkit 路径>"
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Unity YAML .prefab 里的脚本引用行，例：
#   m_Script: {fileID: 11500000, guid: 305b12a83390f5c488a64145b53f92bd, type: 3}
SCRIPT_REF_RE = re.compile(
    r"m_Script:\s*\{\s*fileID:\s*\d+\s*,\s*guid:\s*([0-9a-fA-F]{32})\s*,", re.IGNORECASE
)


def build_script_guid_map(toolkit_dir: str) -> dict[str, str]:
    """扫描 Toolkit 的 Assets/Scripts 下所有 .meta，返回 {guid: 脚本路径}。

    Unity 里每个 .cs 同目录必有一个同名 .meta，其中 guid: xxxx 是脚本的全局标识，
    prefab 的 m_Script 靠它定位脚本类。
    """
    script_dir = Path(toolkit_dir)
    guid_map: dict[str, str] = {}
    meta_count = 0
    matched_cs = 0
    for meta_path in script_dir.rglob("*.cs.meta"):
        meta_count += 1
        text = meta_path.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"^guid:\s*([0-9a-fA-F]+)", text, re.MULTILINE)
        if not m:
            continue
        guid = m.group(1).lower()
        cs_path = meta_path.with_suffix("").with_suffix(".cs")  # Foo.cs.meta -> Foo.cs
        guid_map[guid] = str(cs_path)
        if cs_path.exists():
            matched_cs += 1
    return guid_map


def build_plugin_guid_map(assets_dir: str) -> dict[str, str]:
    """扫描工程 Assets 下的 Plugins/*.dll.meta 与 Scripts/ModCode/**/*.cs.meta，
    返回这些『mod 自有脚本』的 {guid: 路径}。

    mod 的自定义脚本要么以程序集 DLL 形式(Plugins)存在、要么以反编译源码(ModCode)
    存在，它们的 guid 不在 Toolkit 脚本表内；自检时应把它俩纳入，否则自定义引用会被
    误判为『缺失』。
    """
    d = Path(assets_dir)
    guid_map: dict[str, str] = {}
    for meta_path in d.rglob("*.dll.meta"):
        text = meta_path.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"^guid:\s*([0-9a-fA-F]+)", text, re.MULTILINE)
        if m:
            guid_map[m.group(1).lower()] = str(meta_path.with_suffix("").with_suffix(".dll"))
    modcode = d / "Scripts" / "ModCode"
    if modcode.is_dir():
        for meta_path in modcode.rglob("*.cs.meta"):
            text = meta_path.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"^guid:\s*([0-9a-fA-F]+)", text, re.MULTILINE)
            if m:
                guid_map[m.group(1).lower()] = str(meta_path.with_suffix("").with_suffix(".cs"))
    return guid_map


def scan_prefab_script_guids(prefab_path: str) -> list[str]:
    """从 .prefab 文本提取所有 m_Script 引用的 guid（去重、保序）。"""
    text = Path(prefab_path).read_text(encoding="utf-8", errors="ignore")
    guids: list[str] = []
    seen: set[str] = set()
    for g in SCRIPT_REF_RE.findall(text):
        g = g.lower()
        if g not in seen:
            seen.add(g)
            guids.append(g)
    return guids


def verify_prefab_script_refs(
    prefab_path: str, guid_map: dict[str, str]
) -> dict[str, object]:
    """检查一个 .prefab 的所有 m_Script 引用是否在 Toolkit 中命中。

    返回 {"file", "total_refs", "matched", "missing", "match_list", "missing_list"}。
    matched==total_refs 且 missing==[] 即代表“全部识别，不挂”。
    """
    guids = scan_prefab_script_guids(prefab_path)
    matched = []
    missing = []
    for g in guids:
        target = guid_map.get(g)
        if target:
            matched.append({"guid": g, "script": Path(target).name})
        else:
            missing.append(g)
    return {
        "file": Path(prefab_path).name,
        "total_refs": len(guids),
        "matched": len(matched),
        "missing": len(missing),
        "match_list": matched,
        "missing_list": missing,
    }


def verify_all_parts(toolkit_root: str) -> dict[str, object]:
    """对整个 Toolkit 的 Resources/Parts 所有部件 prefab 全部做免挂校验。"""
    parts_dir = Path(toolkit_root) / "Assets" / "Resources" / "Parts"
    script_dir = Path(toolkit_root) / "Assets" / "Scripts"

    guid_map = build_script_guid_map(script_dir)

    results = []
    total_refs = total_matched = total_missing = 0
    missing_any = []
    prefab_files = sorted(parts_dir.rglob("*.prefab"))
    for prefab in prefab_files:
        r = verify_prefab_script_refs(prefab, guid_map)
        total_refs += r["total_refs"]
        total_matched += r["matched"]
        total_missing += r["missing"]
        results.append(r)
        if r["missing"]:
            missing_any.append(r["file"])

    return {
        "toolkit_root": toolkit_root,
        "script_meta_count": len(guid_map),
        "parts_prefab_count": len(prefab_files),
        "total_script_refs": total_refs,
        "total_matched": total_matched,
        "total_missing": total_missing,
        "missing_any_prefabs": missing_any,
        "per_prefab": results,
    }


if __name__ == "__main__":
    import sys

    root = sys.argv[1] if len(sys.argv) > 1 else "/data/user/work/sfs-mtk/Modding Toolkit"
    report = verify_all_parts(root)

    print("=" * 60)
    print(f"Toolkit 根目录 : {report['toolkit_root']}")
    print(f"扫描到脚本 .meta 数 : {report['script_meta_count']}")
    print(f"部件 prefab 数 : {report['parts_prefab_count']}")
    print(f"脚本引用总数 : {report['total_script_refs']}")
    print(f"命中 Toolkit : {report['total_matched']} ✅")
    print(f"缺失(unmatched) : {report['total_missing']}")
    print("=" * 60)

    if report["missing_any_prefabs"]:
        print("存在未命中脚本引用的 prefab:")
        print("" + "\n".join(report["missing_any_prefabs"]))
    else:
        print("🎉 所有部件 prefab 的 m_Script 引用全部命中 Toolkit 脚本 提取后不会挂")
        print("(内置引擎组件如 Transform/MeshRenderer 不在脚本表内 由 Unity 自带)")

    print("\n--- 抽样明细 前 3 个部件 ---")
    for r in report["per_prefab"][:3]:
        print(f"[{r['file']}] 引用 {r['total_refs']} 命中 {r['matched']} 缺失 {r['missing']}")
        for item in r["match_list"]:
            print(f"    ↳ {item['guid']}  ->  {item['script']}")