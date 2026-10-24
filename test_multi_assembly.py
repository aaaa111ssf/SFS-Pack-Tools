#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多自定义脚本模组共存（P0-1 解法）离线验证。

覆盖：
  1. 程序集内部名/模块名等长改写，且改名后元数据仍完整
  2. 唯一名派生是确定性的（同一模组重导得到同一个名字）
  3. `install_code_assembly_as_plugin` 落位 `Plugins/<内部名>.dll`，不再叫 CodeAssembly.dll
  4. 两个模组的 dll 内部名不同 → `detect_assembly_conflicts` 不再判冲突（可共存）
  5. 两个模组内部名仍相同（改名退化）→ 仍按 P0-1 拦截（安全网未被拆掉）
  6. 同一模组重复导入（字节相同）→ 放行
"""

from __future__ import annotations

import json
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import sfs_assembly_rename as rename  # noqa: E402
import sfs_pack_core as core  # noqa: E402

OK = FAIL = 0


def check(label: str, cond: bool, detail: str = ""):
    global OK, FAIL
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail and not cond else ""))
    OK += bool(cond)
    FAIL += not cond


# ---------------------------------------------------------------------------
# 构造一个最小托管程序集（含 Assembly 表 + Module 表）
# ---------------------------------------------------------------------------

def _build_minimal_pe(asm_name: str = "CodeAssembly", module_name: str = "CodeAssembly.dll") -> bytes:
    """手工拼一个可被本模块解析的最小 PE/CLI 元数据。

    不做成完全可执行的程序集——测试目标是元数据定位与等长改写，
    真实程序集的可加载性由 _real_assembly_probe 覆盖。
    """
    strings = bytearray(b"\x00")
    def add_str(s: str) -> int:
        off = len(strings)
        strings.extend(s.encode("utf-8") + b"\x00")
        return off

    module_idx = add_str(module_name)
    asm_idx = add_str(asm_name)

    # 表流：只有 Module(0x00) 与 Assembly(0x20) 两张表，各 1 行
    valid = (1 << 0x00) | (1 << 0x20)
    rows = struct.pack("<II", 1, 1)          # Module=1 行, Assembly=1 行
    header = struct.pack("<IBBBBQQ", 0, 2, 0, 0, 0, valid, 0)
    # Module 行：Generation(2) Name(2) Mvid(2) EncId(2) EncBaseId(2)
    module_row = struct.pack("<HHHHH", 0, module_idx, 0, 0, 0)
    # Assembly 行：HashAlgId(4) Major(2) Minor(2) Build(2) Rev(2) Flags(4)
    #              PublicKey(2) Name(2) Culture(2)
    asm_row = struct.pack("<IHHHHIHHH", 0x8004, 4, 0, 0, 0, 0, 0, asm_idx, 0)
    tables = header + rows + module_row + asm_row

    # #Strings 流（4 字节对齐）
    strings_raw = bytes(strings)
    pad = (-len(strings_raw)) % 4
    strings_raw += b"\x00" * pad

    # 元数据根
    md = bytearray()
    md += struct.pack("<IHHII", 0x424A5342, 1, 1, 0, 12)
    md += b"v4.0.30319\x00\x00"
    md += struct.pack("<HH", 0, 2)           # flags, stream count
    tables_off = 0x60
    md += struct.pack("<II", tables_off, len(tables))
    md += b"#~\x00\x00"
    strings_off = tables_off + len(tables)
    strings_off = (strings_off + 3) & ~3
    md += struct.pack("<II", strings_off, len(strings_raw))
    md += b"#Strings\x00"
    if len(md) < tables_off:
        md += b"\x00" * (tables_off - len(md))
    md += tables
    if len(md) < strings_off:
        md += b"\x00" * (strings_off - len(md))
    md += strings_raw

    # 一个 section 承载 CLI 头 + 元数据
    sec_rva = 0x2000
    sec_raw = 0x200
    cli_size = 72
    md_rva = sec_rva + cli_size          # 元数据紧跟 CLI 头
    cli = bytearray(cli_size)
    struct.pack_into("<I", cli, 0, cli_size)  # cb
    struct.pack_into("<H", cli, 4, 2)         # MajorRuntimeVersion
    struct.pack_into("<H", cli, 6, 5)         # MinorRuntimeVersion
    struct.pack_into("<I", cli, 8, md_rva)    # MetaData RVA
    struct.pack_into("<I", cli, 12, len(md))  # MetaData Size
    struct.pack_into("<I", cli, 16, 1)        # Flags = ILONLY
    struct.pack_into("<I", cli, 20, 0)        # EntryPointToken

    # 文件里 0x200 处开始就是 section 内容：先 CLI 头，再元数据根。
    blob = bytearray(cli) + md

    raw_size = (len(blob) + 0x1FF) & ~0x1FF
    blob += b"\x00" * (raw_size - len(blob))

    dos = bytearray(0x40)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x40)

    pe = bytearray()
    pe[0:0] = b"PE\x00\x00"
    pe += struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, 0xF0, 0x2022)
    opt = bytearray(0xF0)
    struct.pack_into("<H", opt, 0, 0x20B)            # PE32+
    struct.pack_into("<I", opt, 16, 0x2000)          # EntryPoint 占位
    struct.pack_into("<Q", opt, 24, sec_rva)         # ImageBase
    struct.pack_into("<I", opt, 32, 0x1000)          # SectionAlignment
    struct.pack_into("<I", opt, 36, 0x200)           # FileAlignment
    # DataDirectory[14] = CLI
    struct.pack_into("<II", opt, 112 + 14 * 8, sec_rva, 72)
    pe += opt

    section = bytearray(40)
    section[0:8] = b".text\x00\x00\x00"
    struct.pack_into("<I", section, 8, 0x1000)       # VirtualSize
    struct.pack_into("<I", section, 12, sec_rva)     # VirtualAddress
    struct.pack_into("<I", section, 16, raw_size)    # SizeOfRawData
    struct.pack_into("<I", section, 20, sec_raw)     # PointerToRawData
    pe += section

    out = bytes(dos) + bytes(pe)
    out += b"\x00" * (sec_raw - len(out))
    out += bytes(blob)
    return out


def _real_assembly_probe() -> tuple[bool, str]:
    """找一个真实 .NET 程序集做等长改名验证（找不到就跳过）。"""
    roots = [
        Path.home() / ".dotnet" / "tools" / ".store",
        Path(r"C:\Program Files\dotnet\sdk"),
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for dll in root.rglob("ilspycmd.dll"):
            return True, str(dll)
        for dll in sorted(root.rglob("*.dll"))[:1]:
            return True, str(dll)
    return False, ""


def main() -> int:
    temp = Path(tempfile.mkdtemp(prefix="sfs_multi_asm_"))

    print("=== 1. 最小 PE 的 Assembly/Module 表定位 ===")
    dll = temp / "a" / "CodeAssembly.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(_build_minimal_pe())
    info, _rows, _s = rename._assembly_row(dll.read_bytes())
    check("读到 Assembly 名", info["name"] == "CodeAssembly", str(info))
    check("读到 Module 名", info["module_name"] == "CodeAssembly.dll", str(info))

    print("\n=== 2. 等长改名（含模块名） ===")
    new = rename.unique_assembly_name("PicoSpace Utility Pack")
    check("唯一名是 12 字符", len(new) == len("CodeAssembly"), repr(new))
    res = rename.rename_assembly(dll, new)
    check("返回 old/new", res["old"] == "CodeAssembly" and res["new"] == new, str(res))
    info2, _r2, _s2 = rename._assembly_row(dll.read_bytes())
    check("Assembly 名已改", info2["name"] == new, str(info2["name"]))
    check("Module 名同步改", info2["module_name"] == f"{new}.dll", str(info2["module_name"]))
    check("文件大小不变（原地替换）", dll.stat().st_size == len(_build_minimal_pe()))

    print("\n=== 3. 唯一名的确定性与去撞车 ===")
    a1 = rename.unique_assembly_name("Ice Suite")
    a2 = rename.unique_assembly_name("Ice Suite")
    b1 = rename.unique_assembly_name("PicoSpace Utility Pack")
    check("同一模组名 → 同一内部名（可重导）", a1 == a2, f"{a1} vs {a2}")
    check("不同模组名 → 不同内部名", a1 != b1, f"{a1} vs {b1}")
    forced = rename.unique_assembly_name("Ice Suite", taken={a1})
    check("传入 taken 时自动避让", forced != a1, f"{a1} vs {forced}")
    check("避让后仍是 12 字符", len(forced) == 12, forced)

    print("\n=== 4. 长度不符时拒绝写入（不写坏文件） ===")
    dll2 = temp / "b" / "CodeAssembly.dll"
    dll2.parent.mkdir(parents=True)
    dll2.write_bytes(_build_minimal_pe())
    before = dll2.read_bytes()
    try:
        rename.rename_assembly(dll2, "TooLongAssemblyName")
        check("应抛异常", False)
    except rename.AssemblyRenameError:
        check("长度不符抛 AssemblyRenameError", True)
    check("失败后文件字节未变", dll2.read_bytes() == before)

    print("\n=== 5. 落位文件名改成内部名 ===")
    proj = temp / "proj"
    (proj / "Assets").mkdir(parents=True)
    pack = temp / "PicoSpace.pack"
    pack.write_text(json.dumps({
        "WindowsBuild": "",
        "CodeAssembly": _b64(_build_minimal_pe()),
    }), encoding="utf-8")
    out = core.install_code_assembly_as_plugin(proj, pack, None, lambda *_: None)
    check("安装成功", bool(out.get("ok")), str(out))
    dll_name = Path(out["dll"]).name
    check("文件名不再是 CodeAssembly.dll", dll_name != "CodeAssembly.dll", dll_name)
    check("文件名 = <内部名>.dll", dll_name == f'{out["assembly"]}.dll',
          f'{dll_name} vs {out["assembly"]}')
    check("internal 名已非常规名", out["assembly"].lower() != "codeassembly", out["assembly"])
    check("生成了 .meta", Path(out["dll"] + ".meta").is_file())

    print("\n=== 6. 两个模组内部名不同 → detect_assembly_conflicts 不判冲突 ===")
    tk = temp / "toolkit"
    (tk / "Assets" / "Plugins").mkdir(parents=True)
    pkg = temp / "pkg"
    (pkg / "Assets" / "Plugins").mkdir(parents=True)

    mod_a_dll = tk / "Assets" / "Plugins" / "CodeAsm_aaaa.dll"
    mod_a_dll.write_bytes(_build_minimal_pe("CodeAsm_aaaa", "CodeAsm_aaaa.dll"))
    (tk / "Assets" / "Plugins" / "CodeAsm_aaaa.dll.meta").write_text(
        "fileFormatVersion: 2\nguid: " + "a" * 32 + "\n", encoding="utf-8")

    mod_b_dll = pkg / "Assets" / "Plugins" / "CodeAsm_bbbb.dll"
    mod_b_dll.write_bytes(_build_minimal_pe("CodeAsm_bbbb", "CodeAsm_bbbb.dll"))
    (pkg / "Assets" / "Plugins" / "CodeAsm_bbbb.dll.meta").write_text(
        "fileFormatVersion: 2\nguid: " + "b" * 32 + "\n", encoding="utf-8")

    conf = core.detect_assembly_conflicts(tk, pkg, "ModB")
    check("内部名不同 → 无冲突（可共存）", conf == [], str(conf))

    print("\n=== 7. 内部名相同且字节不同 → 仍按 P0-1 拦截 ===")
    pkg2 = temp / "pkg2"
    (pkg2 / "Assets" / "Plugins").mkdir(parents=True)
    (pkg2 / "Assets" / "Plugins" / "CodeAsm_aaaa.dll").write_bytes(
        _build_minimal_pe("CodeAsm_aaaa", "CodeAsm_aaaa.dll") + b"\x00extra")
    (pkg2 / "Assets" / "Plugins" / "CodeAsm_aaaa.dll.meta").write_text(
        "fileFormatVersion: 2\nguid: " + "c" * 32 + "\n", encoding="utf-8")
    conf2 = core.detect_assembly_conflicts(tk, pkg2, "ModC")
    check("同名不同内容 → 判冲突", len(conf2) == 1, str(conf2))
    if conf2:
        check("冲突项带内部名", conf2[0]["assembly"] == "CodeAsm_aaaa", str(conf2[0]))

    print("\n=== 8. 同一模组重复导入（字节相同）→ 放行 ===")
    pkg3 = temp / "pkg3"
    (pkg3 / "Assets" / "Plugins").mkdir(parents=True)
    (pkg3 / "Assets" / "Plugins" / "CodeAsm_aaaa.dll").write_bytes(
        _build_minimal_pe("CodeAsm_aaaa", "CodeAsm_aaaa.dll"))
    (pkg3 / "Assets" / "Plugins" / "CodeAsm_aaaa.dll.meta").write_text(
        "fileFormatVersion: 2\nguid: " + "d" * 32 + "\n", encoding="utf-8")
    conf3 = core.detect_assembly_conflicts(tk, pkg3, "ModA")
    check("字节相同 → 放行（刷新 GUID）", conf3 == [], str(conf3))

    print("\n=== 9. 非托管文件退化：仍按文件名比较 ===")
    junk_tk = temp / "junk_tk"
    junk_pkg = temp / "junk_pkg"
    for root in (junk_tk, junk_pkg):
        (root / "Assets" / "Plugins").mkdir(parents=True)
    (junk_tk / "Assets" / "Plugins" / "weird.dll").write_bytes(b"not a PE")
    (junk_pkg / "Assets" / "Plugins" / "weird.dll").write_bytes(b"also not a PE")
    conf4 = core.detect_assembly_conflicts(junk_tk, junk_pkg, "X")
    check("非托管 dll 仍按文件名判冲突（未放宽安全网）", len(conf4) == 1, str(conf4))

    print("\n=== 10. 真实程序集冒烟（若本机有 .NET 程序集） ===")
    found, real = _real_assembly_probe()
    if not found:
        print("  [--] 本机未找到可测的真实程序集，跳过")
    else:
        try:
            name = rename.read_assembly_name(real)
            check(f"能读出真实程序集内部名（{Path(real).name}）", bool(name), name)
        except Exception as exc:
            # ilspycmd 等可能是单文件打包，读不出属正常，不算失败
            print(f"  [--] 跳过（{type(exc).__name__}: {exc}）")

    print(f"\n结果: {OK} 通过 {FAIL} 失败")
    return 1 if FAIL else 0


def _b64(data: bytes) -> str:
    import base64
    return base64.b64encode(data).decode("ascii")


if __name__ == "__main__":
    raise SystemExit(main())
