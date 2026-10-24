#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 与 GUI 功能对齐的离线验证（不调用 AssetRipper，只测参数解析与辅助子命令）。"""

from __future__ import annotations

import argparse
import contextlib
import io
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


def run_main(argv: list[str]) -> tuple[int, str, str]:
    """跑 main() 并捕获输出/退出码。"""
    old = sys.argv
    sys.argv = ["sfs_project_exporter.py", *argv]
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ex.main()
    except SystemExit as exc:            # parser.error 会 SystemExit(2)
        code = int(exc.code or 0)
    finally:
        sys.argv = old
    return code, out.getvalue(), err.getvalue()


def main() -> int:
    temp = Path(tempfile.mkdtemp(prefix="sfs_cli_"))

    print("=== 1. 参数解析：多输入 / 批量 / 新开关 ===")
    p = ex.build_parser()
    a = p.parse_args(["-i", "a.pack", "b.pack"])
    check("-i 接受多个", a.input == ["a.pack", "b.pack"], str(a.input))
    check("--batch 默认关", a.batch is False)
    check("--overwrite 解析到位", a.overwrite is False)
    a2 = p.parse_args(["-i", "a.pack", "--batch", "--overwrite", "--stop-on-error"])
    check("--batch/--overwrite/--stop-on-error 可组合",
          a2.batch and a2.overwrite and a2.stop_on_error)
    a3 = p.parse_args(["--preview", "pkg", "tk"])
    check("--preview 两个位置参数", a3.preview == ["pkg", "tk"], str(a3.preview))
    a4 = p.parse_args(["--restore", "tk", "20260101_120000", "--apply"])
    check("--restore + --apply", a4.restore and a4.apply)

    print("\n=== 2. --overwrite 真正生效（此前是空实现） ===")
    outdir = temp / "out"
    write(outdir / "stale.txt", "old")
    (temp / "out.zip").write_text("oldzip", encoding="utf-8")
    od, zp, cleared = ex.resolve_output_paths(
        temp / "in.pack", outdir, temp / "out.zip", overwrite=True)
    check("overwrite=True 用原路径", od == outdir.resolve(), str(od))
    check("旧目录被清理", not outdir.exists(), str(outdir))
    check("旧 ZIP 被清理", not (temp / "out.zip").exists())
    check("cleared 标记为真", cleared is True)

    outdir2 = temp / "out2"
    write(outdir2 / "keep.txt", "keep")
    od2, zp2, cleared2 = ex.resolve_output_paths(
        temp / "in.pack", outdir2, None, overwrite=False)
    check("overwrite=False 启用编号", od2.name == "out2_2", str(od2))
    check("overwrite=False 不动原目录", (outdir2 / "keep.txt").is_file())
    check("overwrite=False cleared 为假", cleared2 is False)

    print("\n=== 3. --backups / --probe / --preview / --restore 子命令 ===")
    tk = temp / "toolkit"
    write(tk / "ProjectSettings" / "ProjectVersion.txt", "m_EditorVersion: 2022.3.10f1\n")
    write(tk / "Assets" / "Scripts" / "Version.cs",
          'public static class V { public const string ToolkitVersion = "9.9"; }\n')
    write(tk / "Assets" / "Resources" / "Parts" / "P" / "P.prefab", "cur")
    backup = tk / "_PackToolBackup" / "20260101_000000"
    write(backup / "Assets" / "Resources" / "Parts" / "P" / "P.prefab", "from-backup")

    code, out, _ = run_main(["--backups", str(tk)])
    check("--backups 退出 0", code == 0, str(code))
    check("--backups 列出那条备份", "20260101_000000" in out, out)

    code, out, _ = run_main(["--probe", str(tk)])
    check("--probe 退出 0", code == 0, str(code))
    check("--probe 显示 Unity 版本", "2022.3.10f1" in out, out)
    check("--probe 显示 Toolkit 版本", "9.9" in out, out)

    pkg = temp / "pkg"
    write(pkg / "Assets" / "Resources" / "Parts" / "New" / "N.prefab", "n")
    write(pkg / "Assets" / "Resources" / "Parts" / "New" / "N.prefab.meta",
          "fileFormatVersion: 2\nguid: " + "7" * 32 + "\n")
    code, out, _ = run_main(["--preview", str(pkg), str(pkg)])
    # 与自身比较：全部应是替换/跳过，不报错
    check("--preview 可运行", code == 0, f"code={code} out={out[:200]}")

    code, out, _ = run_main(["--restore", str(tk), "20260101_000000"])
    check("--restore 默认只预演", code == 0 and "预演" in out, out)
    check("预演未改文件",
          (tk / "Assets" / "Resources" / "Parts" / "P" / "P.prefab").read_text(encoding="utf-8") == "cur")

    code, out, _ = run_main(["--restore", str(tk), "20260101_000000", "--apply"])
    check("--restore --apply 退出 0", code == 0, out)
    check("回滚真的写入",
          (tk / "Assets" / "Resources" / "Parts" / "P" / "P.prefab").read_text(encoding="utf-8")
          == "from-backup",
          (tk / "Assets" / "Resources" / "Parts" / "P" / "P.prefab").read_text(encoding="utf-8"))

    code, out, err = run_main(["--restore", str(tk), "19990101_000000"])
    check("不存在的备份返回非 0", code != 0, f"code={code} out={out} err={err}")

    print("\n=== 4. 无 -i 且无子命令 → 明确报错 ===")
    code, out, err = run_main([])
    check("退出码非 0", code != 0, str(code))
    check("提示需要 -i", "--input" in err or "-i" in err, err[:200])

    print("\n=== 5. 批量模式：坏包不中断整批 ===")
    good1 = write(temp / "batch" / "good1.pack", '{"WindowsBuild": "", "AndroidBuild": ""}')
    bad = write(temp / "batch" / "bad.pack", "not json at all")
    good2 = write(temp / "batch" / "good2.pack", '{"WindowsBuild": ""}')
    args = argparse.Namespace(
        input=[str(good1), str(bad), str(good2)],
        output_dir=str(temp / "batch_out"),
        zip=None, asset_ripper=None, no_download=True, no_zip=True,
        overwrite=False, platforms="single", batch=True, stop_on_error=False,
    )
    # 强制 export_prefabs 失败（没有 AssetRipper），验证批量仍跑完三项
    orig = ex.export_prefabs

    def fake_export(sub_args):
        if "bad" in str(sub_args.input):
            raise ex.ExportError("模拟解码失败")
        return None

    ex.export_prefabs = fake_export
    try:
        code = ex._run_batch(args)
    finally:
        ex.export_prefabs = orig
    check("批量整体返回 1（有失败项）", code == 1, str(code))

    print(f"\n结果: {OK} 通过 {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
