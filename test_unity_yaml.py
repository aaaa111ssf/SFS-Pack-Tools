#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UnityYAML 稳健解析验证：等价写法全覆盖 + 与旧正则的差异对比。

核心断言：旧正则失配的写法，新解析器必须能正确识别并重写；
且重写后**除 guid 值以外一个字符都不变**。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import sfs_unity_yaml as uy  # noqa: E402
import sfs_pack_core as core  # noqa: E402

OK = FAIL = 0

OLD_GUID = "a" * 32
NEW_GUID = "b" * 32
MAP = {OLD_GUID: NEW_GUID}


def check(label: str, cond: bool, detail: str = ""):
    global OK, FAIL
    print(f"  [{'OK ' if cond else 'FAIL'}] {label}" + (f"  → {detail}" if detail and not cond else ""))
    OK += bool(cond)
    FAIL += not cond


def old_rewrite(text: str) -> tuple[str, int]:
    """旧正则实现的入口，用于对比。

    注意不能调 `core.rewrite_script_guids`——它现在会分发到新解析器，
    对比就失去意义了。直接调被保留下来做兜底的那份正则实现。
    """
    return core._rewrite_script_guids_regex(text, MAP)


def new_rewrite(text: str) -> tuple[str, int]:
    return uy.rewrite_script_guids_stable(text, MAP)


def main() -> int:
    print("=== 1. 标准写法：新旧一致 ===")
    standard = (
        "--- !u!114 &400\n"
        "MonoBehaviour:\n"
        "  m_Script: {fileID: 11500000, guid: " + OLD_GUID + ", type: 3}\n"
        "  m_Name: \n"
    )
    o_text, o_n = old_rewrite(standard)
    n_text, n_n = new_rewrite(standard)
    check("旧正则能改标准写法", o_n == 1, f"n={o_n}")
    check("新解析器也能改", n_n == 1, f"n={n_n}")
    check("两者结果完全一致", o_text == n_text, f"{o_text!r} vs {n_text!r}")

    print("\n=== 2. 字段顺序打乱（旧正则失配） ===")
    reordered = (
        "MonoBehaviour:\n"
        "  m_Script: {guid: " + OLD_GUID + ", fileID: 11500000, type: 3}\n"
    )
    o_text, o_n = old_rewrite(reordered)
    n_text, n_n = new_rewrite(reordered)
    check("旧正则漏掉（0 次替换）", o_n == 0, f"n={o_n}")
    check("新解析器能改", n_n == 1, f"n={n_n}")
    check("新文本含新 guid", NEW_GUID in n_text)
    check("其余字符未变", n_text.replace(NEW_GUID, OLD_GUID) == reordered)
    refs = uy.iter_script_refs(reordered)
    check("解析出 fileID", refs and refs[0].file_id == "11500000", str(refs))
    check("解析出 type", refs and refs[0].type_ == "3", str(refs))

    print("\n=== 3. block style（旧正则失配） ===")
    block = (
        "MonoBehaviour:\n"
        "  m_Script:\n"
        "    fileID: 11500000\n"
        "    guid: " + OLD_GUID + "\n"
        "    type: 3\n"
        "  m_Name: test\n"
    )
    o_text, o_n = old_rewrite(block)
    n_text, n_n = new_rewrite(block)
    check("旧正则漏掉", o_n == 0, f"n={o_n}")
    check("新解析器能改", n_n == 1, f"n={n_n}")
    check("新文本含新 guid", NEW_GUID in n_text)
    check("块缩进与其它字段未变", n_text.replace(NEW_GUID, OLD_GUID) == block,
          repr(n_text))

    print("\n=== 4. 空格任意 / 无空格（旧正则部分失配） ===")
    cases = {
        "紧凑无空格": "  m_Script: {fileID:11500000,guid:" + OLD_GUID + ",type:3}\n",
        "多空格": "  m_Script:   {  fileID :  11500000 ,  guid :  " + OLD_GUID + "  ,  type :  3  }\n",
        "制表符": "  m_Script:\t{fileID: 11500000,\tguid:\t" + OLD_GUID + ",\ttype: 3}\n",
    }
    for name, text in cases.items():
        _ot, on = old_rewrite(text)
        nt, nn = new_rewrite(text)
        check(f"{name}：新解析器能改", nn == 1, f"n={nn} old={on}")
        check(f"{name}：仅 guid 变化", nt.replace(NEW_GUID, OLD_GUID) == text, repr(nt))

    print("\n=== 5. guid 带引号 ===")
    quoted = "  m_Script: {fileID: 11500000, guid: '" + OLD_GUID + "', type: 3}\n"
    nt, nn = new_rewrite(quoted)
    check("引号 guid 能识别并替换", nn == 1 and NEW_GUID in nt, f"n={nn} {nt!r}")
    check("引号本身保留", "'" + NEW_GUID + "'" in nt, repr(nt))

    print("\n=== 6. 大小写混写 ===")
    mixed = OLD_GUID.upper()[:16] + OLD_GUID[16:]
    text_mixed = "  m_Script: {fileID: 11500000, guid: " + mixed + ", type: 3}\n"
    nt, nn = new_rewrite(text_mixed)
    check("大写 guid 也能命中（MAP 用小写键）", nn == 1, f"n={nn} guid={mixed}")

    print("\n=== 7. 不应误伤的情形 ===")
    # 非 m_Script 的 guid 不能被改（比如贴图引用）
    texture_ref = (
        "  m_Texture: {fileID: 2800000, guid: " + OLD_GUID + ", type: 3}\n"
    )
    nt, nn = new_rewrite(texture_ref)
    check("非 m_Script 的 guid 不动", nn == 0 and nt == texture_ref, f"n={nn}")

    # 不在映射里的 guid 不动
    other = "  m_Script: {fileID: 11500000, guid: " + "c" * 32 + ", type: 3}\n"
    nt, nn = new_rewrite(other)
    check("未命中映射时原文不动", nn == 0 and nt == other)

    # 注释里的 m_Script 不该被当真（保守：只认带 guid 字段的 mapping）
    commented = "  # m_Script: {fileID: 11500000, guid: " + OLD_GUID + ", type: 3}\n"
    nt, nn = new_rewrite(commented)
    check("注释行保持原样（不误改）", nt == commented, f"n={nn}")

    print("\n=== 8. 一个文件里多条引用 ===")
    multi = (
        "--- !u!114 &1\n"
        "MonoBehaviour:\n"
        "  m_Script: {fileID: 11500000, guid: " + OLD_GUID + ", type: 3}\n"
        "--- !u!114 &2\n"
        "MonoBehaviour:\n"
        "  m_Script: {guid: " + OLD_GUID + ", fileID: 11500000, type: 3}\n"
        "--- !u!114 &3\n"
        "MonoBehaviour:\n"
        "  m_Script:\n"
        "    guid: " + OLD_GUID + "\n"
        "    fileID: 11500000\n"
    )
    refs = uy.iter_script_refs(multi)
    check("识别出 3 条引用", len(refs) == 3, str(len(refs)))
    check("三种写法都被标记", [r.style for r in refs] == ["flow", "flow", "block"],
          str([r.style for r in refs]))
    nt, nn = new_rewrite(multi)
    check("三条全部替换", nn == 3, f"n={nn}")
    check("替换后不含旧 guid", OLD_GUID not in nt.lower(), nt)
    check("替换后 3 个新 guid", nt.count(NEW_GUID) == 3, str(nt.count(NEW_GUID)))

    print("\n=== 9. 幂等性 ===")
    once, _ = new_rewrite(multi)
    twice, n2 = new_rewrite(once)
    check("二次重写 0 次替换", n2 == 0, f"n={n2}")
    check("二次结果与一次相同", twice == once)

    print("\n=== 10. 其它 guid 工具 ===")
    guids = uy.iter_guid_values("guid: " + OLD_GUID + "\n  m_Texture: {fileID: 1, guid: " + "d" * 32 + "}")
    check("iter_guid_values 找到 2 个", len(guids) == 2, str(guids))
    masked = uy.mask_guids("a: guid: " + OLD_GUID + " b: guid: " + "e" * 32)
    check("mask_guids 抹掉全部", OLD_GUID not in masked and "e" * 32 not in masked, masked)
    check("mask 保留占位符", masked.count("guid: <G>") == 2, masked)

    print("\n=== 11. 畸形输入不崩 ===")
    for bad in ("", "m_Script: {", "m_Script: {guid: ", "m_Script: {\n guid: x\n",
                "m_Script: {fileID: 1, guid: " + "z" * 32 + ", type: 3}"):
        try:
            uy.iter_script_refs(bad)
            uy.rewrite_script_guids_stable(bad, MAP)
            ok = True
        except Exception:
            ok = False
        check(f"畸形输入不抛异常: {bad[:28]!r}", ok)

    print("\n=== 12. 与 core 集成：真实 prefab 片段 ===")
    real = (
        "%YAML 1.1\n"
        "%TAG !u! tag:unity3d.com,2011:\n"
        "--- !u!1 &1234567890\n"
        "GameObject:\n"
        "  m_ObjectHideFlags: 0\n"
        "  m_CorrespondingSourceObject: {fileID: 0}\n"
        "  m_PrefabInstance: {fileID: 0}\n"
        "  m_PrefabAsset: {fileID: 0}\n"
        "  serializedVersion: 6\n"
        "  m_Component:\n"
        "  - component: {fileID: 1234567891}\n"
        "  m_Layer: 0\n"
        "  m_Name: Engine\n"
        "  m_TagString: Untagged\n"
        "--- !u!114 &1234567891\n"
        "MonoBehaviour:\n"
        "  m_ObjectHideFlags: 0\n"
        "  m_CorrespondingSourceObject: {fileID: 0}\n"
        "  m_PrefabInstance: {fileID: 0}\n"
        "  m_PrefabAsset: {fileID: 0}\n"
        "  m_GameObject: {fileID: 1234567890}\n"
        "  m_Enabled: 1\n"
        "  m_EditorHideFlags: 0\n"
        "  m_Script: {fileID: 11500000, guid: " + OLD_GUID + ", type: 3}\n"
        "  m_Name: \n"
        "  m_EditorClassIdentifier: \n"
        "  mass: 10\n"
    )
    nt, nn = new_rewrite(real)
    check("真实片段能改", nn == 1, f"n={nn}")
    check("整段结构未变", nt.replace(NEW_GUID, OLD_GUID) == real)
    check("m_GameObject 引用未被误改", "{fileID: 1234567890}" in nt)

    print(f"\n结果: {OK} 通过 {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
