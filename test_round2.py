#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第二轮补全项的验证：增量落地、AssetRipper 版本可选、GUI 入口存在。

与 test_toolbox / test_cli 的区别：这里只验证「新接线的部分」——
库函数早已存在，重点是它们**真的接进了流程**。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import sfs_project_exporter as ex  # noqa: E402
import sfs_pack_toolbox as tb  # noqa: E402

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


def main() -> int:
    temp = Path(tempfile.mkdtemp(prefix="sfs_round2_"))

    print("=== 1. AssetRipper 版本可选：参数与解析分支 ===")
    p = ex.build_parser()
    a = p.parse_args(["-i", "x.pack", "--asset-ripper-version", "1.0.1"])
    check("--asset-ripper-version 解析到位", a.asset_ripper_version == "1.0.1",
          str(a.asset_ripper_version))
    a_none = p.parse_args(["-i", "x.pack"])
    check("默认不指定版本", a_none.asset_ripper_version is None)

    # 指定版本 + 禁下载 + 无缓存 → 必须报错，不能静默退回内置版
    try:
        ex.resolve_asset_ripper(None, auto_download=False, version="1.0.1")
        check("指定版本但无缓存时报错", False, "没有抛异常")
    except ex.ExportError as exc:
        check("指定版本但无缓存时报错", True)
        check("错误信息点明版本", "1.0.1" in str(exc), str(exc))

    # 显式路径优先级最高（哪怕同时给了 version）
    fake = write(temp / "fake_ripper.exe", "MZ")
    got = ex.resolve_asset_ripper(str(fake), auto_download=False, version="9.9.9")
    check("显式路径优先于 version", Path(got) == fake.resolve(), str(got))

    print("\n=== 2. 增量：库层判断链 ===")
    pack = write(temp / "mod.pack", '{"WindowsBuild": ""}')
    tk = temp / "toolkit"
    write(tk / "ProjectSettings" / "ProjectVersion.txt", "m_EditorVersion: 2021.3.16f1\n")
    write(tk / "Assets" / "Scripts" / "S.cs", "public class S { }\n")
    write(tk / "Assets" / "Resources" / "Parts" / "M" / "MP.prefab", "p")
    idx = temp / "export_index.json"

    first = tb.incremental_plan(pack, tk, idx, toolkit_fingerprint="fp")
    check("首次导出 → full", first["action"] == "full", str(first))

    tb.record_export(idx, pack, parts=["MP"], toolkit_fingerprint="fp")
    check("索引文件已写出", idx.is_file())
    saved = json.loads(idx.read_text(encoding="utf-8"))
    check("索引含 pack 条目", bool(saved.get("packs")), str(list(saved)))

    second = tb.incremental_plan(pack, tk, idx, toolkit_fingerprint="fp")
    check("未变化 → skip", second["action"] == "skip", str(second))

    changed = tb.incremental_plan(pack, tk, idx, toolkit_fingerprint="fp2")
    check("Toolkit 指纹变 → full", changed["action"] == "full", str(changed))

    # 换包
    write(pack, '{"WindowsBuild": "", "X": "y"}')
    repack = tb.incremental_plan(pack, tk, idx, toolkit_fingerprint="fp")
    check("包变化 → full", repack["action"] == "full", str(repack))

    print("\n=== 3. 增量：GUI 已接线 ===")
    # 用静态检查确认接线存在（不启动 GUI，避免 CI 无显示环境失败）
    src = (ROOT / "sfs_pack_tool_gui.py").read_text(encoding="utf-8")
    check("GUI 引用 incremental_plan", "incremental_plan" in src)
    check("GUI 引用 record_export", "record_export" in src)
    check("GUI 有 _export_index_path", "def _export_index_path" in src)
    check("GUI 有增量勾选框", "incremental_var" in src)
    check("导出前判断、导出后记录",
          src.index("incremental_plan") < src.index("record_export"))

    print("\n=== 4. 批量：GUI 入口已接线 ===")
    check("GUI 有 start_batch", "def start_batch" in src)
    check("GUI 有 _export_one", "def _export_one" in src)
    check("GUI 使用 BatchPlan", "BatchPlan" in src)
    check("批量按钮已加入界面", 'self.t("batch")' in src)

    print("\n=== 5. UnityYAML 已接入 core ===")
    core_src = (ROOT / "sfs_pack_core.py").read_text(encoding="utf-8")
    check("core 引用 sfs_unity_yaml", "sfs_unity_yaml" in core_src)
    check("保留了正则兜底实现", "_rewrite_script_guids_regex" in core_src)
    check("rewrite_script_guids 走解析器",
          "rewrite_script_guids_stable" in core_src)
    # 兜底必须真的还能用
    import sfs_pack_core as core
    txt = "  m_Script: {fileID: 11500000, guid: " + "a" * 32 + ", type: 3}\n"
    out, n = core._rewrite_script_guids_regex(txt, {"a" * 32: "b" * 32})
    check("正则兜底仍可用", n == 1 and "b" * 32 in out, f"n={n}")
    # 主路径：乱序写法
    reordered = "  m_Script: {guid: " + "a" * 32 + ", fileID: 11500000, type: 3}\n"
    out2, n2 = core.rewrite_script_guids(reordered, {"a" * 32: "b" * 32})
    check("core 主路径能处理乱序", n2 == 1 and "b" * 32 in out2, f"n={n2}")

    print("\n=== 6. 端到端：增量记录 → 判断 闭环 ===")
    tk2 = temp / "tk2"
    write(tk2 / "ProjectSettings" / "ProjectVersion.txt", "m_EditorVersion: 2022.3.1f1\n")
    write(tk2 / "Assets" / "Scripts" / "S.cs", "public class S2 { }\n")
    write(tk2 / "Assets" / "Resources" / "Parts" / "Z" / "Z.prefab", "z")
    pack2 = write(temp / "mod2.pack", '{"WindowsBuild": ""}')
    idx2 = temp / "idx2.json"
    fp2 = tb.probe_toolkit_version(tk2)["fingerprint"]
    check("探测到指纹", len(fp2) == 40, fp2)

    plan = tb.incremental_plan(pack2, tk2, idx2, toolkit_fingerprint=fp2)
    check("首次 full", plan["action"] == "full")
    tb.record_export(idx2, pack2, parts=["Z"], toolkit_fingerprint=fp2)
    plan = tb.incremental_plan(pack2, tk2, idx2, toolkit_fingerprint=fp2)
    check("闭环后 skip", plan["action"] == "skip", str(plan))

    # 脚本变更导致指纹变，必须重新全量
    write(tk2 / "Assets" / "Scripts" / "S.cs", "public class S3 { }\n")
    fp3 = tb.probe_toolkit_version(tk2)["fingerprint"]
    check("脚本变化指纹变化", fp3 != fp2)
    plan = tb.incremental_plan(pack2, tk2, idx2, toolkit_fingerprint=fp3)
    check("指纹变后 full", plan["action"] == "full", str(plan))

    print(f"\n结果: {OK} 通过 {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
