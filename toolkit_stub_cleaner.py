#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清理 Toolkit 工程里混入的 AssetRipper 占位 stub。

这些 stub 与 Toolkit 真脚本同名同类，会让 Unity 报 CS0101 重复定义。
默认只列清单不删文件（dry run），确认无误后加 --apply 才真正删除，
删除前会在同目录生成一份 stub 备份（*.stub.bak）以便回滚。

用法：
    python toolkit_stub_cleaner.py                   列出会删哪些（不动文件）
    python toolkit_stub_cleaner.py --apply           真正删除
    python toolkit_stub_cleaner.py --root <路径>     指定别的 Toolkit 根目录
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = Path(
    r"D:/Spaceflight-Simulator--ModdingToolkit-c94139072a809a92753396d2f57d4c4b51791bc2/Modding Toolkit12"
)


def load_keep_alive():
    spec = importlib.util.spec_from_file_location("keep_alive", HERE / "sfs_pack_core.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["keep_alive"] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(DEFAULT_ROOT), help="Toolkit 工程根目录")
    ap.add_argument("--apply", action="store_true", help="真正删除（默认只列清单）")
    args = ap.parse_args()

    ka = load_keep_alive()
    root = Path(args.root)
    scripts = root / "Assets" / "Scripts"
    if not scripts.is_dir():
        print(f"不是有效的 Toolkit 工程 未找到 {scripts}")
        return 2

    dups = ka.find_duplicate_types(scripts)
    skip = sorted(ka.stub_conflicts(scripts))

    print(f"Toolkit 根目录 {root}")
    print(f"重复类型定义 {len(dups)} 个")
    print(f"待清理 stub  {len(skip)} 个")
    print()

    for fq, (files, solid) in sorted(dups.items()):
        marks = []
        for f in files:
            tag = "STUB" if ka.is_asset_ripper_stub(f) else "real"
            marks.append(f"{tag} {f.relative_to(scripts).as_posix()}")
        print(f"  {fq}")
        for m in marks:
            print(f"      - {m}")

    if not args.apply:
        print()
        print("以上是 dry run 未删除任何文件")
        print("确认清单无误后执行: python toolkit_stub_cleaner.py --apply")
        return 0

    print()
    removed = 0
    for cs in skip:
        for f in (cs, Path(str(cs) + ".meta")):
            if not f.is_file():
                continue
            bak = f.with_suffix(f.suffix + ".stub.bak")
            try:
                shutil.copy2(f, bak)
                f.unlink()
            except OSError as exc:
                print(f"  [!] 删除失败 {f} {exc}")
                continue
        removed += 1
        print(f"  - {cs.relative_to(scripts).as_posix()}")

    print()
    print(f"已删除 {removed} 个 stub 每个文件都留有 .stub.bak 备份")
    print("用 Unity 打开工程确认无 CS0101 后 可自行搜索删除 *.stub.bak")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
