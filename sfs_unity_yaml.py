#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""稳健的 Unity YAML 引用解析：替代原先脆弱的单行正则。

为什么需要它
------------
旧实现用一条正则匹配 `m_Script` 引用：

    m_Script:\\s*\\{\\s*fileID:\\s*\\d+\\s*,\\s*guid:\\s*([0-9a-f]{32})\\s*,\\s*type:\\s*3\\s*\\}

它隐含了三个强假设，每一条在真实工程里都可能不成立：

1. **字段顺序固定** fileID → guid → type。UnityYAML 是合法 YAML，flow mapping
   的键顺序在解析层面没有语义，手工编辑/第三方工具改写过就未必是这个顺序。
2. **必须是单行 flow style**。以下是等价写法，旧正则全部失配：

       m_Script: {guid: xxx, fileID: 11500000, type: 3}     # 顺序变了
       m_Script:
         fileID: 11500000                                    # block style
         guid: xxx
         type: 3
       m_Script: {fileID: 11500000,   guid:  xxx ,type:3}    # 空格任意

3. **只认 32 位小写/大写十六进制**。Unity 写的是小写，但做过 sed 处理的文件
   可能出现大小写混写——这个旧正则靠 IGNORECASE 恰好能过，属于运气。

失配的后果是**静默的**：`rewrite_script_guids` 返回 0 次替换，调用方以为
「本来就不需要改」，于是那个 prefab 的脚本引用永远不修，最后报 missing script，
而日志里一行异常都没有。

本模块的做法
------------
不重排、不重写整个文件，只做「精确的局部替换」：

1. 找到 `m_Script` 键（含引号/无引号两种写法）；
2. 从它后面解析出一个 mapping（`{...}` flow 或缩进 block），取出 fileID/guid/type；
3. 只把 guid 值那一段的字节换掉，其余字符原样保留。

这样既能认识各种等价的 YAML 写法，又不会因为重新序列化而改动 Unity 文件的
格式细节（缩进、引号风格、字段顺序、注释），把风险限制在最小范围。

对外接口
--------
    iter_script_refs(text)                -> [(span, ref)]  ref={fileid, guid, type}
    rewrite_script_guids_stable(text, m)  -> (new_text, count)   m 为 {旧guid: 新guid}
    iter_guid_values(text)                -> [(span, guid)]  任意 guid: 值
    mask_guids(text)                      -> 把 guid 值替换成占位符
"""

from __future__ import annotations

import re

__all__ = [
    "ScriptRef",
    "iter_script_refs",
    "rewrite_script_guids_stable",
    "iter_guid_values",
    "mask_guids",
    "count_script_refs",
]

# 键名：允许 `m_Script:` 或 `"m_Script":`（Unity 不写引号，但别因此炸掉）
_KEY_RE_TMPL = r"""(?:"{k}"|'{k}'|{k})\s*:"""
GUID_VALUE_RE = re.compile(r"[0-9a-fA-F]{32}")

# 一个「字段名: 值」的简单行/片段
_FIELD_RE = re.compile(r"(?P<key>[A-Za-z_][\w]*)\s*:\s*(?P<val>[^,\n}\r]*)")
# 值里只允许这些，避免把文件里别处的 guid 误吞
_GUID_ONLY_RE = re.compile(r"^[0-9a-fA-F]{32}$")


class ScriptRef:
    """一条 m_Script 引用。

    span 是 guid **值本身**在原文中的 (start, end)，用于局部替换。
    """

    __slots__ = ("start", "end", "guid", "file_id", "type_", "style", "key_end")

    def __init__(self, start: int, end: int, guid: str, file_id: str, type_: str,
                 style: str, key_end: int):
        self.start = start
        self.end = end
        self.guid = guid
        self.file_id = file_id
        self.type_ = type_
        self.style = style          # "flow" | "block"
        self.key_end = key_end      # m_Script 键结束位置（调试用）

    def __repr__(self) -> str:
        return (f"ScriptRef(guid={self.guid!r}, fileID={self.file_id!r}, "
                f"type={self.type_!r}, {self.style}, span={self.start}:{self.end})")


def _skip_ws(text: str, pos: int, *, stop_at_newline: bool = False) -> int:
    n = len(text)
    while pos < n:
        ch = text[pos]
        if ch in " \t":
            pos += 1
            continue
        if ch in "\r\n":
            if stop_at_newline:
                return pos
            pos += 1
            continue
        return pos
    return pos


def _parse_flow_mapping(text: str, open_pos: int) -> tuple[int, dict[str, tuple[int, int, str]]]:
    """解析从 `{` 开始的 flow mapping，返回 (结束位置, {键: (值起, 值止, 原值)})。

    只做浅层解析：值里出现嵌套 `{}` 时按括号配平跳过（m_Script 实际不会出现，
    但别让畸形文件把扫描带偏）。
    """
    assert text[open_pos] == "{"
    pos = open_pos + 1
    fields: dict[str, tuple[int, int, str]] = {}
    depth = 0
    n = len(text)
    while pos < n:
        pos = _skip_ws(text, pos)
        if pos >= n:
            break
        ch = text[pos]
        if ch == "}":
            if depth == 0:
                return pos + 1, fields
            depth -= 1
            pos += 1
            continue
        if ch == "{":
            depth += 1
            pos += 1
            continue
        m = _FIELD_RE.match(text, pos)
        if not m:
            pos += 1
            continue
        key = m.group("key")
        val_start = m.start("val")
        val_end = m.end("val")
        # 值里若含嵌套结构，跳到配平的右括号之后再截断
        cursor = val_end
        if "{" in m.group("val"):
            local_depth = 0
            while cursor < n:
                if text[cursor] == "{":
                    local_depth += 1
                elif text[cursor] == "}":
                    local_depth -= 1
                    if local_depth == 0:
                        cursor += 1
                        break
                cursor += 1
            val_end = cursor
        # 去掉首尾空白后再记录，保证 span 精确指向值本身
        raw = text[val_start:val_end]
        lead = len(raw) - len(raw.lstrip())
        trail = len(raw) - len(raw.rstrip())
        start = val_start + lead
        end = max(start, val_end - trail)
        fields[key] = (start, end, text[start:end].strip())
        pos = val_end
    return pos, fields


def _parse_block_mapping(text: str, start: int, base_indent: int) -> tuple[int, dict[str, tuple[int, int, str]]]:
    """解析缩进式 block mapping（m_Script: 换行后逐行写字段）。"""
    fields: dict[str, tuple[int, int, str]] = {}
    pos = start
    n = len(text)
    while pos < n:
        line_start = pos
        line_end = text.find("\n", pos)
        if line_end < 0:
            line_end = n
        line = text[line_start:line_end]
        if not line.strip():
            pos = line_end + 1
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        if indent <= base_indent:
            break                                  # 回到上层，block 结束
        m = _FIELD_RE.match(line.strip())
        if m:
            val = m.group("val").strip()
            col = line_start + len(line) - len(line.lstrip()) + m.start("val")
            start_ = col + (len(m.group("val")) - len(m.group("val").lstrip()))
            fields[m.group("key")] = (start_, start_ + len(val), val)
        pos = line_end + 1
    return pos, fields


def _comment_ranges(text: str) -> list[tuple[int, int]]:
    """找出全部 `#` 注释的区间（Unity YAML 的注释只到行尾，且 `#` 在引号内不算）。

    不能简单按 `#` 切：Unity 的字符串值里可能出现 `#`（如颜色 `#FF0000`、
    名称里带井号），那属于内容而不是注释。
    """
    ranges: list[tuple[int, int]] = []
    pos = 0
    n = len(text)
    in_single = in_double = False
    line_start = 0
    while pos < n:
        ch = text[pos]
        if ch == "\n":
            if in_single or in_double:
                # 引号跨行在 Unity YAML 里不合法，遇到换行就重置，避免一个坏引号吞掉全文
                in_single = in_double = False
            pos += 1
            line_start = pos
            continue
        if in_double:
            if ch == "\\":
                pos += 2
                continue
            if ch == '"':
                in_double = False
            pos += 1
            continue
        if in_single:
            if ch == "'":
                if pos + 1 < n and text[pos + 1] == "'":   # '' 转义
                    pos += 2
                    continue
                in_single = False
            pos += 1
            continue
        if ch == '"':
            in_double = True
            pos += 1
            continue
        if ch == "'":
            in_single = True
            pos += 1
            continue
        if ch == "#":
            # `#` 只在行首或前面是空白时才是注释（YAML 规范）
            if pos == line_start or text[pos - 1] in " \t":
                end = text.find("\n", pos)
                end = n if end < 0 else end
                ranges.append((pos, end))
                pos = end
                continue
        pos += 1
    return ranges


def _in_ranges(pos: int, ranges: list[tuple[int, int]]) -> bool:
    for start, end in ranges:
        if start <= pos < end:
            return True
        if pos < start:
            break
    return False


def iter_script_refs(text: str) -> list[ScriptRef]:
    """扫描全部 `m_Script` 引用，兼容 flow / block 两种写法与任意字段顺序。

    注释里的 `m_Script:` 会被跳过：否则对一份「整行被注释掉」的历史 prefab
    执行重写，会改到注释内容，虽然不影响 Unity 解析，但会让 diff 变得难读、
    也让「本次改了几处引用」的统计虚高。
    """
    key_re = re.compile(_KEY_RE_TMPL.format(k="m_Script"))
    comments = _comment_ranges(text)
    out: list[ScriptRef] = []
    for km in key_re.finditer(text):
        if comments and _in_ranges(km.start(), comments):
            continue
        after = km.end()
        pos = _skip_ws(text, after)
        fields: dict[str, tuple[int, int, str]] = {}
        style = "flow"
        if pos < len(text) and text[pos] == "{":
            _end, fields = _parse_flow_mapping(text, pos)
        else:
            # block style：m_Script: 换行 + 缩进字段
            line_end = text.find("\n", after)
            rest_of_line = text[after:line_end if line_end >= 0 else len(text)].strip()
            if rest_of_line:
                continue                            # 不是我们认识的形式，跳过
            base_indent = len(text[:after]) - len(text[:after].rstrip(" ")) - 1
            style = "block"
            _end, fields = _parse_block_mapping(text, (line_end + 1) if line_end >= 0 else len(text),
                                                max(base_indent, 0))
        g = fields.get("guid")
        if not g:
            continue
        # guid 字段本身若落在注释里，同样跳过
        if comments and _in_ranges(g[0], comments):
            continue
        start, end, guid_val = g
        if not _GUID_ONLY_RE.match(guid_val):
            # guid 可能带引号
            stripped = guid_val.strip("'\"")
            if not _GUID_ONLY_RE.match(stripped):
                continue
            # 引号内的偏移也要对上
            q = guid_val.find(stripped)
            start, end = start + q, start + q + len(stripped)
            guid_val = stripped
        out.append(ScriptRef(
            start=start, end=end, guid=guid_val,
            file_id=fields.get("fileID", (0, 0, ""))[2],
            type_=fields.get("type", (0, 0, ""))[2],
            style=style, key_end=km.end(),
        ))
    return out


def count_script_refs(text: str) -> int:
    return len(iter_script_refs(text))


def rewrite_script_guids_stable(text: str, mapping: dict[str, str]) -> tuple[str, int]:
    """把命中的 m_Script guid 换成新值，返回 (新文本, 替换次数)。

    与旧 `rewrite_script_guids` 语义一致：只替换 `mapping` 里有的 guid，
    其余字符（空白、字段顺序、缩进）**一字不动**。
    """
    if not mapping:
        return text, 0
    refs = iter_script_refs(text)
    if not refs:
        return text, 0
    pieces: list[str] = []
    cursor = 0
    changed = 0
    for ref in refs:
        key = ref.guid.lower()
        new_guid = mapping.get(ref.guid) or mapping.get(key)
        if not new_guid:
            continue
        if ref.start < cursor:
            continue
        pieces.append(text[cursor:ref.start])
        pieces.append(new_guid)
        cursor = ref.end
        changed += 1
    if not changed:
        return text, 0
    pieces.append(text[cursor:])
    return "".join(pieces), changed


# 任意 `guid:` 值（含 .meta 的 guid 行、材质里的内联引用）
_GUID_FIELD_RE = re.compile(r"guid\s*:\s*([0-9a-fA-F]{32})")


def iter_guid_values(text: str) -> list[tuple[int, int, str]]:
    """产出文本里全部 `guid: xxx` 的 (start, end, guid)，start/end 指向 guid 值。"""
    out: list[tuple[int, int, str]] = []
    for m in _GUID_FIELD_RE.finditer(text):
        out.append((m.start(1), m.end(1), m.group(1)))
    return out


def mask_guids(text: str, placeholder: str = "guid: <G>") -> str:
    """把所有 guid 值替换成占位符，用于「两份资产内容是否等价」的比较。"""
    pieces: list[str] = []
    cursor = 0
    for start, end, _g in iter_guid_values(text):
        if start < cursor:
            continue
        pieces.append(text[cursor:start])
        pieces.append(placeholder)
        cursor = end
    if not pieces:
        return text
    pieces.append(text[cursor:])
    return "".join(pieces)
