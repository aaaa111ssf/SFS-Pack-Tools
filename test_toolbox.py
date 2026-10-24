#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sfs_pack_toolbox 功能验证：回滚 / 预览 / 版本探测 / 日志 / 增量 / 批量。

全部离线、纯文件系统，不依赖 Unity 或 AssetRipper。
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

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


def meta_guid(guid: str) -> str:
    return f"fileFormatVersion: 2\nguid: {guid}\n"


def make_toolkit(root: Path) -> Path:
    """造一个最小 Toolkit 工程。"""
    write(root / "ProjectSettings" / "ProjectVersion.txt", "m_EditorVersion: 2021.3.16f1\n")
    write(root / "Assets" / "Scripts" / "Parts" / "Part.cs",
          "namespace SFS.Parts { public class Part : UnityEngine.MonoBehaviour { } }\n",
          )
    write(root / "Assets" / "Scripts" / "Version.cs",
          'namespace SFS { public static class V { public const string ToolkitVersion = "2.3"; } }\n')
    write(root / "Assets" / "Resources" / "Parts" / "Stock" / "StockPart.prefab", "stock\n")
    return root


def main() -> int:
    temp = Path(tempfile.mkdtemp(prefix="sfs_toolbox_"))

    # ------------------------------------------------------------------
    print("=== 1. 备份列举 ===")
    tk = make_toolkit(temp / "toolkit")
    backups_root = tk / "_PackToolBackup"
    b1 = backups_root / "20260101_120000"
    write(b1 / "Assets" / "Resources" / "Parts" / "ModA" / "P.prefab", "old-a")
    write(b1 / "Assets" / "Resources" / "Parts" / "ModA" / "P.prefab.meta", meta_guid("1" * 32))
    b2 = backups_root / "20260102_130000_stubshaders"
    write(b2 / "Assets" / "Shaders" / "SFS_Weird.shader", "// stub")
    b3 = backups_root / "20260103_140000_dangling"
    write(b3 / "dangling_manifest.txt", "# 清单\n")
    write(backups_root / "not-a-backup-dir" / "x.txt", "ignore me")

    listed = tb.list_backups(tk)
    check("只认出 3 条合规备份", len(listed) == 3, str([e.path.name for e in listed]))
    check("按时间倒序（新在前）", listed[0].timestamp == "20260103_140000",
          listed[0].timestamp)
    kinds = {e.timestamp: e.kind for e in listed}
    check("解析出 kind", kinds.get("20260102_130000") == "stubshaders", str(kinds))
    check("普通备份 kind 为空", kinds.get("20260101_120000") == "", str(kinds))
    check("识别清单文件", listed[0].manifest == "dangling_manifest.txt", listed[0].manifest)

    # ------------------------------------------------------------------
    print("\n=== 2. 回滚预演不写任何文件 ===")
    target_prefab = tk / "Assets" / "Resources" / "Parts" / "ModA" / "P.prefab"
    write(target_prefab, "current-version")
    dry = tb.restore_backup(tk, "20260101_120000", dry_run=True)
    check("预演成功", dry["ok"], str(dry))
    check("报告将还原数量", dry.get("would_restore", 0) >= 1, str(dry))
    check("预演后文件内容未变", target_prefab.read_text(encoding="utf-8") == "current-version")

    # ------------------------------------------------------------------
    print("\n=== 3. 真正回滚（并先备份现状） ===")
    done = tb.restore_backup(tk, "20260101_120000", dry_run=False, safety_backup=True)
    check("回滚成功", done["ok"], str(done))
    check("文件已还原成旧内容",
          target_prefab.read_text(encoding="utf-8") == "old-a",
          target_prefab.read_text(encoding="utf-8"))
    pre = done.get("pre_backup", "")
    check("生成了 prerestore 备份", bool(pre) and Path(pre).is_dir(), pre)
    if pre:
        saved = list(Path(pre).rglob("P.prefab"))
        check("现状已被备份", len(saved) == 1, str(saved))
        if saved:
            check("备份的正是回滚前内容",
                  saved[0].read_text(encoding="utf-8") == "current-version",
                  saved[0].read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    print("\n=== 4. 合并预览：新增/替换/跳过分类 ===")
    tk2 = make_toolkit(temp / "toolkit2")
    pkg = temp / "pkg"
    # 新增文件
    write(pkg / "Assets" / "Resources" / "Parts" / "ModB" / "NewPart.prefab", "new-part")
    write(pkg / "Assets" / "Resources" / "Parts" / "ModB" / "NewPart.prefab.meta", meta_guid("2" * 32))
    # 同名同 GUID（替换）
    write(pkg / "Assets" / "Resources" / "Parts" / "Stock" / "StockPart.prefab", "stock-v2")
    write(pkg / "Assets" / "Resources" / "Parts" / "Stock" / "StockPart.prefab.meta", meta_guid("3" * 32))
    write(tk2 / "Assets" / "Resources" / "Parts" / "Stock" / "StockPart.prefab.meta", meta_guid("3" * 32))
    # 同名不同 GUID（跳过）
    write(pkg / "Assets" / "Textures" / "T.png", "png")
    write(pkg / "Assets" / "Textures" / "T.png.meta", meta_guid("4" * 32))
    write(tk2 / "Assets" / "Textures" / "T.png", "png-existing")
    write(tk2 / "Assets" / "Textures" / "T.png.meta", meta_guid("5" * 32))
    # 缺 .meta（冲突/需注意）
    write(pkg / "Assets" / "Textures" / "NoMeta.png", "png")

    pv = tb.preview_merge(pkg, tk2)
    check("预览成功", pv["ok"], str(pv))
    rels_add = {a["rel"] for a in pv["adds"]}
    check("识别新增 prefab",
          "Resources/Parts/ModB/NewPart.prefab" in rels_add, str(sorted(rels_add)))
    check("识别同名同 GUID 为替换",
          any(r["rel"].endswith("StockPart.prefab") for r in pv["replaces"]),
          str(pv["replaces"]))
    check("识别同名不同 GUID 为跳过",
          any(s["rel"].endswith("T.png") for s in pv["skips"]), str(pv["skips"]))
    check("识别缺 .meta 的隐患",
          any(c["rel"].endswith("NoMeta.png") for c in pv["conflicts"]), str(pv["conflicts"]))
    check("新部件名单含 NewPart", "NewPart" in pv["parts_added"], str(pv["parts_added"]))
    check("Toolkit 已有部件名单含 StockPart",
          "StockPart" in pv["parts_existing"], str(pv["parts_existing"]))
    check("预览不写文件",
          not (tk2 / "Assets" / "Resources" / "Parts" / "ModB").exists())

    lines = tb.format_preview(pv)
    check("预览可转成人类可读行", len(lines) >= 2 and "新增" in lines[0], str(lines[:2]))

    # ------------------------------------------------------------------
    print("\n=== 5. Toolkit 版本探测与指纹 ===")
    probe = tb.probe_toolkit_version(tk2)
    check("探测成功", probe["ok"], str(probe))
    check("读到 Unity 版本", probe["unity_version"] == "2021.3.16f1", probe["unity_version"])
    check("读到 Toolkit 版本", probe["toolkit_version"] == "2.3", probe["toolkit_version"])
    check("指纹非空", len(probe["fingerprint"]) == 40, probe["fingerprint"])

    probe_again = tb.probe_toolkit_version(tk2)
    check("指纹稳定（同工程两次一致）",
          probe["fingerprint"] == probe_again["fingerprint"])
    check("compare 同值 → same",
          tb.compare_toolkit_fingerprint(probe["fingerprint"], probe_again["fingerprint"]) == "same")
    check("compare 异值 → changed",
          tb.compare_toolkit_fingerprint("a" * 40, "b" * 40) == "changed")
    check("compare 缺值 → unknown",
          tb.compare_toolkit_fingerprint("", "b" * 40) == "unknown")

    # 改一个脚本，指纹必须变
    write(tk2 / "Assets" / "Scripts" / "Parts" / "Part.cs",
          "namespace SFS.Parts { public class Part : UnityEngine.MonoBehaviour { public int x; } }\n")
    probe_changed = tb.probe_toolkit_version(tk2)
    check("改脚本后指纹变化", probe_changed["fingerprint"] != probe["fingerprint"])
    check("compare 检测到变化",
          tb.compare_toolkit_fingerprint(probe["fingerprint"], probe_changed["fingerprint"]) == "changed")

    bad = tb.probe_toolkit_version(temp / "nonexistent")
    check("不存在的工程返回 ok=False", not bad["ok"], str(bad))

    # ------------------------------------------------------------------
    print("\n=== 6. 诊断日志与可分享报告 ===")
    logdir = temp / "logs"
    with tb.DiagnosticLog(logdir, app_version="2.3.4", keep_days=30) as dlog:
        dlog.info("第一行")
        dlog("第二行（__call__ 别名）")
        report = dlog.close(extra={"mod.pack": "abc.pack", "Toolkit": "2.3"})
    check("日志文件已生成", (logdir / f"{dlog.stamp}.log").is_file())
    check("报告已生成", bool(report) and Path(report).is_file(), report)
    if report:
        text = Path(report).read_text(encoding="utf-8")
        check("报告含版本号", "2.3.4" in text)
        check("报告含 extra 信息", "abc.pack" in text and "2.3" in text)
        check("报告含日志正文", "第一行" in text and "第二行" in text)
        check("报告自带 Python 版本", "3.10" in text or "Python" in text)

    # 过期日志自动清理
    old = logdir / "20000101_000000.log"
    write(old, "very old")
    old_time = time.time() - 90 * 86400
    import os
    os.utime(old, (old_time, old_time))
    with tb.DiagnosticLog(logdir, app_version="2.3.4", keep_days=30):
        pass
    check("过期日志被清理", not old.exists())

    # ------------------------------------------------------------------
    print("\n=== 7. 增量导出判断 ===")
    pack = write(temp / "modX.pack", '{"WindowsBuild": "", "CodeAssembly": ""}')
    idx_path = temp / "export_index.json"
    tk3 = make_toolkit(temp / "toolkit3")
    write(tk3 / "Assets" / "Resources" / "Parts" / "ModX" / "PX.prefab", "x")

    plan1 = tb.incremental_plan(pack, tk3, idx_path, toolkit_fingerprint="fp1")
    check("首次 → full", plan1["action"] == "full", str(plan1))
    check("首次原因合理", "首次" in plan1["reason"], plan1["reason"])

    tb.record_export(idx_path, pack, parts=["PX"], toolkit_fingerprint="fp1")
    plan2 = tb.incremental_plan(pack, tk3, idx_path, toolkit_fingerprint="fp1")
    check("包与 Toolkit 未变 → skip", plan2["action"] == "skip", str(plan2))

    plan3 = tb.incremental_plan(pack, tk3, idx_path, toolkit_fingerprint="fp2")
    check("Toolkit 指纹变 → full", plan3["action"] == "full", str(plan3))
    check("原因提示换版本", "Toolkit" in plan3["reason"], plan3["reason"])

    # 包内容变化
    write(pack, '{"WindowsBuild": "", "CodeAssembly": "changed"}')
    plan4 = tb.incremental_plan(pack, tk3, idx_path, toolkit_fingerprint="fp1")
    check("包内容变 → full", plan4["action"] == "full", str(plan4))

    # 部件被删
    tb.record_export(idx_path, pack, parts=["PX"], toolkit_fingerprint="fp1")
    (tk3 / "Assets" / "Resources" / "Parts" / "ModX" / "PX.prefab").unlink()
    plan5 = tb.incremental_plan(pack, tk3, idx_path, toolkit_fingerprint="fp1")
    check("部件已不在 Toolkit → full", plan5["action"] == "full", str(plan5))
    check("报告缺失部件", plan5["missing_parts"] == ["PX"], str(plan5["missing_parts"]))

    # ------------------------------------------------------------------
    print("\n=== 8. 批量导出队列 ===")
    packs = [temp / f"mod{i}.pack" for i in range(3)]
    for p in packs:
        write(p, "{}")
    batch = tb.BatchPlan(packs + [packs[0]], temp / "out")   # 故意重复一个
    check("重复包被去重", len(batch) == 3, str(len(batch)))

    seen: list[str] = []

    def executor(item, log):
        seen.append(item.pack.name)
        if item.pack.name == "mod1.pack":
            raise RuntimeError("模拟失败")
        if item.pack.name == "mod2.pack":
            return "skip"
        return True

    summary = batch.run(executor)
    check("全部跑完（失败不中断）", len(seen) == 3, str(seen))
    check("成功计数", summary["ok"] == 1, str(summary))
    check("失败计数", summary["failed"] == 1, str(summary))
    check("跳过计数", summary["skipped"] == 1, str(summary))
    check("汇总含逐项状态", len(summary["items"]) == 3, str(summary["items"]))

    # stop_on_error
    batch2 = tb.BatchPlan(packs, temp / "out2")
    ran: list[str] = []

    def failing(item, log):
        ran.append(item.pack.name)
        raise RuntimeError("boom")

    batch2.run(failing, stop_on_error=True)
    check("stop_on_error 时立刻停止", len(ran) == 1, str(ran))

    # ------------------------------------------------------------------
    print("\n=== 9. AssetRipper 版本识别（无 exe 时不崩） ===")
    miss = tb.resolve_asset_ripper_version(temp / "nope.exe")
    check("不存在的 exe → ok=False", not miss["ok"], str(miss))
    check("给出错误原因", bool(miss["error"]), str(miss))
    check("推荐版本常量存在", tb.RECOMMENDED_ASSET_RIPPER == "1.1.4")

    print(f"\n结果: {OK} 通过 {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
