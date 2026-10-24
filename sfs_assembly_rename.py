#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯 Python 改写 .NET 程序集的**内部 Assembly 名**（原地等长替换，零第三方依赖）。

为什么需要它
------------
Unity 按「程序集内部名」区分托管插件，文件名不影响解析。两个 mod 各自带
`CodeAssembly.dll` 时，内部名都叫 `CodeAssembly`，Unity 只会保留一份，
另一份的类全部 missing script —— 这就是 P0-1。

把每个 mod 的程序集改成唯一内部名后，两份可以同时存在。

为什么只能等长替换
------------------
`Assembly` 表的 Name 列是 `#Strings` 堆里的**字节偏移**。`#Strings` 后面紧跟着
`#US`/`#GUID`/`#Blob`，改名长度一变就必须重建整个元数据堆与 PE 布局——那等于写
一个完整的 .NET 链接器，风险远大于收益。因此本模块**只做等长原地替换**，
不满足长度时明确报错，绝不写坏文件。

唯一名怎么保证
--------------
`unique_assembly_name()` 生成 **12 字符**（与 `CodeAssembly` 等长）的确定性名字：
`CodeAsm_` + 4 位十六进制。同一个 mod 永远得到同一个名字（可重复导出、可幂等），
不同 mod 用 4 位散列区分；真撞车时调用方传入 `taken` 集合，自动换下一个后缀。

用法
----
    from sfs_assembly_rename import read_assembly_name, rename_assembly, unique_assembly_name

    unique_assembly_name("PicoSpace Utility Pack", taken={"CodeAsm_0000"})
    read_assembly_name(dll)         # -> "CodeAssembly"
    rename_assembly(dll, unique)    # 原地改写，返回 {old, new, bytes}
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

__all__ = [
    "AssemblyRenameError",
    "canonical_assembly_name",
    "read_assembly_name",
    "rename_assembly",
    "unique_assembly_name",
]

# 与 `CodeAssembly` 等长，这样任何 mod 的原始 dll 都能原地替换
TARGET_NAME_LEN = len("CodeAssembly")
NAME_PREFIX = "CodeAsm_"


class AssemblyRenameError(Exception):
    """改名失败（不是 PE、找不到 Assembly 表、长度不符等）。"""


# ---------------------------------------------------------------------------
# PE / CLI 元数据解析
# ---------------------------------------------------------------------------


def _u16(blob, off):
    return struct.unpack_from("<H", blob, off)[0]


def _u32(blob, off):
    return struct.unpack_from("<I", blob, off)[0]


def _pe_sections(blob: bytes) -> list[dict]:
    if len(blob) < 0x40 or blob[:2] != b"MZ":
        raise AssemblyRenameError("不是 PE 文件（缺少 MZ 头）")
    pe_off = _u32(blob, 0x3C)
    if blob[pe_off:pe_off + 4] != b"PE\0\0":
        raise AssemblyRenameError("PE 签名不正确")
    coff = pe_off + 4
    num_sections = _u16(blob, coff + 2)
    opt_size = _u16(blob, coff + 16)
    opt = coff + 20
    magic = _u16(blob, opt)
    data_dir = opt + (112 if magic == 0x20B else 96)
    cli_rva = _u32(blob, data_dir + 14 * 8)
    if not cli_rva:
        raise AssemblyRenameError("这不是托管程序集（没有 CLI 头）")
    sec_off = opt + opt_size
    sections = []
    for i in range(num_sections):
        s = sec_off + i * 40
        sections.append({
            "vsize": _u32(blob, s + 8),
            "vaddr": _u32(blob, s + 12),
            "rawsize": _u32(blob, s + 16),
            "rawptr": _u32(blob, s + 20),
        })
    return sections


def _rva_to_off(sections: list[dict], rva: int) -> int:
    for s in sections:
        if s["vaddr"] <= rva < s["vaddr"] + max(s["vsize"], s["rawsize"]):
            return rva - s["vaddr"] + s["rawptr"]
    raise AssemblyRenameError(f"RVA 0x{rva:x} 未映射到任何节")


def _cli_and_metadata(blob: bytes, sections: list[dict]) -> int:
    pe_off = _u32(blob, 0x3C)
    coff = pe_off + 4
    opt = coff + 20
    magic = _u16(blob, opt)
    data_dir = opt + (112 if magic == 0x20B else 96)
    cli_rva = _u32(blob, data_dir + 14 * 8)
    cli_off = _rva_to_off(sections, cli_rva)
    md_rva = _u32(blob, cli_off + 8)
    return _rva_to_off(sections, md_rva)


def _metadata_streams(blob: bytes, md_off: int) -> dict[str, tuple[int, int]]:
    if _u32(blob, md_off) != 0x424A5342:
        raise AssemblyRenameError("元数据签名不正确")
    ver_len = _u32(blob, md_off + 12)
    p = md_off + 16 + ver_len
    p += 2                       # flags
    n = _u16(blob, p)
    p += 2
    streams: dict[str, tuple[int, int]] = {}
    for _ in range(n):
        off = _u32(blob, p)
        size = _u32(blob, p + 4)
        p += 8
        end = blob.index(b"\0", p)
        name = blob[p:end].decode("ascii", errors="replace")
        p = (end + 1 + 3) & ~3
        streams[name] = (md_off + off, size)
    return streams


# 表行宽：只覆盖到 Assembly(0x20) 之前可能出现的表，足够且不会误算。
# ECMA-335 II.24.2.6 复合（coded）索引：宽度由「被引用表中最大行数」决定，
# 阈值 = 2^(16 - 标签位数)。原实现错误地按单表索引宽度算，大程序集会少算字节，
# 使后面的 Assembly 行偏移漂移 → 读出的内部名是空串。
_CODED = {
    # 名称: (被引用表, 标签位数)
    "TypeDefOrRef":        ((0x02, 0x01, 0x1B), 2),
    "HasConstant":         ((0x04, 0x08, 0x17), 2),
    "HasCustomAttribute":  ((0x06, 0x04, 0x01, 0x02, 0x08, 0x09, 0x0A, 0x00, 0x0E,
                             0x17, 0x14, 0x11, 0x1A, 0x1B, 0x20, 0x23, 0x26, 0x27,
                             0x28, 0x2A, 0x2C, 0x2B), 5),
    "HasFieldMarshal":     ((0x04, 0x08), 1),
    "HasDeclSecurity":     ((0x02, 0x06, 0x20), 2),
    "MemberRefParent":     ((0x02, 0x01, 0x1A, 0x06, 0x1B), 3),
    "HasSemantics":        ((0x14, 0x17), 1),
    "MethodDefOrRef":      ((0x06, 0x0A), 1),
    "MemberForwarded":     ((0x04, 0x06), 1),
    "Implementation":      ((0x26, 0x23, 0x27), 2),
    "CustomAttributeType": ((0x06, 0x0A), 3),
    "ResolutionScope":     ((0x00, 0x1A, 0x23, 0x01), 2),
    "TypeOrMethodDef":     ((0x02, 0x06), 1),
}


def _row_size(tid, str_sz, guid_sz, blob_sz, idx, rows=None) -> int:
    """单行字节数。`rows` 用于算 coded 索引宽度（缺省按全 2 字节，仅兼容旧调用）。"""
    rows = rows or {}

    def coded(name: str) -> int:
        tables, bits = _CODED[name]
        mx = max((rows.get(t, 0) for t in tables), default=0)
        return 4 if mx >= (1 << (16 - bits)) else 2

    if tid == 0x00: return 2 + str_sz + guid_sz * 3                 # Module
    if tid == 0x01: return coded("ResolutionScope") + str_sz * 2    # TypeRef
    if tid == 0x02:                                                 # TypeDef
        return 4 + str_sz * 2 + coded("TypeDefOrRef") + idx(0x04) + idx(0x06)
    if tid == 0x03: return idx(0x04)                                # FieldPtr
    if tid == 0x04: return 2 + str_sz + blob_sz                     # Field
    if tid == 0x05: return idx(0x06)                                # MethodPtr
    if tid == 0x06:                                                 # MethodDef
        return 4 + 2 + 2 + str_sz + blob_sz + idx(0x08)
    if tid == 0x07: return idx(0x08)                                # ParamPtr
    if tid == 0x08: return 2 + 2 + str_sz                           # Param
    if tid == 0x09:                                                 # InterfaceImpl
        return idx(0x02) + coded("TypeDefOrRef")
    if tid == 0x0A:                                                 # MemberRef
        return coded("MemberRefParent") + str_sz + blob_sz
    if tid == 0x0B:                                                 # Constant
        return 2 + coded("HasConstant") + blob_sz
    if tid == 0x0C:                                                 # CustomAttribute
        return coded("HasCustomAttribute") + coded("CustomAttributeType") + blob_sz
    if tid == 0x0D: return coded("HasFieldMarshal") + blob_sz       # FieldMarshal
    if tid == 0x0E: return 2 + coded("HasDeclSecurity") + blob_sz   # DeclSecurity
    if tid == 0x0F: return 2 + 4 + idx(0x02)                        # ClassLayout
    if tid == 0x10: return 4 + idx(0x04)                            # FieldLayout
    if tid == 0x11: return blob_sz                                  # StandAloneSig
    if tid == 0x12: return idx(0x02) + idx(0x14)                    # EventMap
    if tid == 0x13: return idx(0x14)                                # EventPtr
    if tid == 0x14: return 2 + str_sz + coded("TypeDefOrRef")       # Event
    if tid == 0x15: return idx(0x02) + idx(0x17)                    # PropertyMap
    if tid == 0x16: return idx(0x17)                                # PropertyPtr
    if tid == 0x17: return 2 + str_sz + blob_sz                     # Property
    if tid == 0x18:                                                 # MethodSemantics
        return 2 + idx(0x06) + coded("HasSemantics")
    if tid == 0x19:                                                 # MethodImpl
        return idx(0x02) + coded("MethodDefOrRef") * 2
    if tid == 0x1A: return str_sz                                   # ModuleRef
    if tid == 0x1B: return blob_sz                                  # TypeSpec
    if tid == 0x1C:                                                 # ImplMap
        return 2 + coded("MemberForwarded") + str_sz + idx(0x1A)
    if tid == 0x1D: return 4 + idx(0x04)                            # FieldRVA
    if tid == 0x1E: return 8                                        # EncLog
    if tid == 0x1F: return 4                                        # EncMap
    if tid == 0x20:                                                 # Assembly
        return 4 + 2 + 2 + 2 + 2 + 4 + blob_sz + str_sz * 2
    if tid == 0x21: return 4                                        # AssemblyProcessor
    if tid == 0x22: return 12                                       # AssemblyOS
    if tid == 0x23:                                                 # AssemblyRef
        return 2 + 2 + 2 + 2 + 4 + blob_sz + str_sz * 2 + blob_sz
    if tid == 0x24: return 4 + idx(0x23)                            # AssemblyRefProcessor
    if tid == 0x25: return 12 + idx(0x23)                           # AssemblyRefOS
    if tid == 0x26: return 4 + str_sz + blob_sz                     # File
    if tid == 0x27:                                                 # ExportedType
        return 4 + 4 + str_sz * 2 + coded("Implementation")
    if tid == 0x28:                                                 # ManifestResource
        return 4 + 4 + str_sz + coded("Implementation")
    if tid == 0x29: return idx(0x02) * 2                            # NestedClass
    if tid == 0x2A:                                                 # GenericParam
        return 2 + 2 + coded("TypeOrMethodDef") + str_sz
    if tid == 0x2B: return coded("MethodDefOrRef") + blob_sz        # MethodSpec
    if tid == 0x2C:                                                 # GenericParamConstraint
        return idx(0x2A) + coded("TypeDefOrRef")
    raise AssemblyRenameError(f"Assembly 表之前出现未支持的表 0x{tid:02x}")


def _locate_assembly_name(blob: bytes) -> tuple[int, str]:
    """返回 (Name 字符串在文件里的绝对偏移, 当前名字)。"""
    idx, _rows, _streams = _assembly_row(blob)
    return idx["name_str_abs"], idx["name"]


def _assembly_row(blob: bytes) -> tuple[dict, dict, dict]:
    """解析出 Assembly 表与 Module 表的 Name 列位置。

    返回 (info, rows, streams)；info 含 name_str_abs / name / module_str_abs / module_name。
    """
    sections = _pe_sections(blob)
    md_off = _cli_and_metadata(blob, sections)
    streams = _metadata_streams(blob, md_off)
    if "#~" not in streams:
        raise AssemblyRenameError("缺少 #~ 表流（加密或混淆的程序集不支持）")
    tables_off = streams["#~"][0]
    strings_off, _ = streams["#Strings"]

    # 表流头：Reserved(4) Major(1) Minor(1) HeapSizes(1) Reserved(1) Valid(8) Sorted(8)
    p = tables_off + 4 + 2        # 跳过 Reserved/Major/Minor
    heap_sizes = blob[p]          # 偏移 +6
    p += 2                        # HeapSizes + Reserved → 偏移 +8
    valid = struct.unpack_from("<Q", blob, p)[0]
    p += 8
    p += 8                        # sorted
    rows: dict[int, int] = {}
    for i in range(64):
        if (valid >> i) & 1:
            rows[i] = _u32(blob, p)
            p += 4

    if 0x20 not in rows:
        raise AssemblyRenameError("没有 Assembly 表（可能是 .netmodule）")

    str_sz = 4 if heap_sizes & 0x01 else 2
    guid_sz = 4 if heap_sizes & 0x02 else 2
    blob_sz = 4 if heap_sizes & 0x04 else 2

    def idx(tid):
        return 4 if rows.get(tid, 0) >= 0x10000 else 2

    def heap_str(idx_value: int) -> tuple[int, str]:
        start = strings_off + idx_value
        end = blob.index(b"\0", start)
        return start, blob[start:end].decode("utf-8", errors="replace")

    def read_idx(table_off: int, size: int) -> int:
        return _u32(blob, table_off) if size == 4 else _u16(blob, table_off)

    # Module 表(0x00) 紧跟行数数组之后，是第 0 张表（存在时）
    info: dict = {}
    cursor = p
    module_str_abs = module_name = ""
    if 0x00 in rows and rows[0x00] >= 1:
        # Module 行：Generation(2) Name(str) Mvid(guid) EncId(guid) EncBaseId(guid)
        module_name_idx = read_idx(cursor + 2, str_sz)
        module_str_abs, module_name = heap_str(module_name_idx)
        info["module_str_abs"] = module_str_abs
        info["module_name"] = module_name

    offset = 0
    for tid in sorted(rows):
        if tid >= 0x20:
            break
        offset += _row_size(tid, str_sz, guid_sz, blob_sz, idx, rows) * rows[tid]

    asm_off = p + offset
    name_col = asm_off + 4 + 2 + 2 + 2 + 2 + 4 + blob_sz
    name_str_abs, name = heap_str(read_idx(name_col, str_sz))
    info.update(name_str_abs=name_str_abs, name=name,
                module_str_abs=info.get("module_str_abs", ""),
                module_name=info.get("module_name", ""))
    return info, rows, streams


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------


def read_assembly_name(path) -> str:
    """读程序集内部名。解析失败或读到空名都抛 AssemblyRenameError。

    空名必须当失败处理：调用方（唯一改名流程）会拿它拼文件名，
    空串会落成 `Assets/Plugins/.dll`——一个 Unity 根本认不出的插件。
    """
    blob = Path(path).read_bytes()
    name = _locate_assembly_name(blob)[1]
    if not name:
        raise AssemblyRenameError("读出的程序集内部名为空（元数据表偏移解析失败）")
    return name


def canonical_assembly_name(mod_name: str) -> str:
    """由模组名推出**确定性**的 12 字符内部名（等长，可原地改写）。"""
    digest = zlib.crc32(str(mod_name).encode("utf-8")) & 0xFFFF
    return f"{NAME_PREFIX}{digest:04x}"          # CodeAsm_ + 4 hex = 12 字符


def unique_assembly_name(mod_name: str, taken: set[str] | None = None) -> str:
    """生成不与 `taken` 冲突的唯一内部名（仍是 12 字符）。"""
    taken = {t.lower() for t in (taken or set())}
    base = canonical_assembly_name(mod_name)
    if base.lower() not in taken:
        return base
    # 撞车：按 4 位十六进制递增找下一个空位
    seed = zlib.crc32(str(mod_name).encode("utf-8"))
    for step in range(1, 0x10000):
        cand = f"{NAME_PREFIX}{(seed + step) & 0xFFFF:04x}"
        if cand.lower() not in taken:
            return cand
    raise AssemblyRenameError("可用程序集名已耗尽（几乎不可能发生）")


def rename_assembly(path, new_name: str, *, rename_module: bool = True) -> dict:
    """原地把程序集内部名改成 `new_name`（必须与原名等长）。

    Module 表里的模块名（通常是 `CodeAssembly.dll`）也按同样规则同步改成
    `<new_name>.dll`——Unity 的 MonoScript 在部分解析路径上会用模块名定位，
    两者不一致会留下隐患。模块名长度不足时只改 Assembly 名并给出警告。

    返回 {path, old, new, bytes, module: {old,new} | None, warning}；
    失败抛 AssemblyRenameError，且**不写文件**。
    """
    p = Path(path)
    raw = p.read_bytes()
    blob = bytearray(raw)
    info, _rows, _streams = _assembly_row(raw)
    start, old = info["name_str_abs"], info["name"]
    old_b = old.encode("utf-8")
    new_b = str(new_name).encode("utf-8")
    if len(new_b) != len(old_b):
        raise AssemblyRenameError(
            f"内部名必须等长：原名 {old!r}({len(old_b)} 字节)，新名 {new_name!r}({len(new_b)} 字节)")

    out = {"path": str(p), "old": old, "new": new_name, "bytes": len(raw),
           "module": None, "warning": ""}

    module_patch = None
    if rename_module and info.get("module_str_abs"):
        mod_old = info["module_name"]
        stem, dot, ext = mod_old.rpartition(".")
        if dot and ext.lower() == "dll":
            mod_new = f"{new_name}.{ext}"
            if len(mod_new.encode()) == len(mod_old.encode()):
                module_patch = (info["module_str_abs"], mod_old, mod_new)
            else:
                out["warning"] = (f"模块名 {mod_old!r} 与 {mod_new!r} 长度不同，已跳过"
                                  f"（只改了程序集内部名）")

    if new_b == old_b and module_patch is None:
        return out

    blob[start:start + len(new_b)] = new_b
    if module_patch is not None:
        m_start, m_old, m_new = module_patch
        blob[m_start:m_start + len(m_new)] = m_new.encode()
        out["module"] = {"old": m_old, "new": m_new}
    p.write_bytes(bytes(blob))
    return out
