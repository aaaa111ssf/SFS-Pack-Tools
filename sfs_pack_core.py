#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""脚本免挂对齐：把导出工程 prefab 的 m_Script GUID 重指向 Modding Toolkit 真脚本。

.prefab 的 MonoBehaviour 靠 m_Script(指向 MonoScript 的 GUID) 定位脚本类；
AssetRipper 生成的 stub GUID 与包内原始引用不一致，打开工程就会 Missing Script。
流程：读回包内脚本类名 → 按类名取 Toolkit GUID → 删 stub(防 CS0101)
→ 整拷 Assets/Scripts(防 CS0246) → 重写 .prefab/.asset → 上报无法解析的类。
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

# Unity YAML 里脚本引用整行，形如：
#   m_Script: {fileID: 11500000, guid: 305b12a83390f5c488a64145b53f92bd, type: 3}
SCRIPT_REF_RE = re.compile(
    r"(m_Script:\s*\{\s*fileID:\s*\d+\s*,\s*guid:\s*)([0-9a-fA-F]{32})(\s*,\s*type:\s*3\s*\})",
    re.IGNORECASE,
)
CLASS_DECL_RE = re.compile(r"\b(?:partial\s+|abstract\s+|sealed\s+|static\s+)*class\s+(\w+)")
COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
# 剥字符串字面量，避免里面的花括号干扰深度统计（含 @"..." 与 $"{...}" 形式）
STRING_RE = re.compile(r'@?"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'')
NS_DECL_RE = re.compile(r"^\s*namespace\s+([\w.]+)", re.MULTILINE)
TYPE_DECL_RE = re.compile(
    r"^\s*(?:\[[^\]\n]*\]\s*)?"
    r"(?:(?:public|internal|private|protected)\s+)?"
    r"(?:(?:abstract|sealed|static|unsafe|readonly|new)\s+)*"
    r"(partial\s+)?"
    r"(?:class|struct|interface|enum)\s+(\w+)",
    re.MULTILINE,
)

PRE_BUILD_KEYS = ("WindowsBuild", "AndroidBuild", "MacBuild", "IOS_Build")

# 反编译出来的作者自定义脚本统一放这个子目录，跟 Toolkit 自带的 Scripts 分开
MOD_CODE_DIRNAME = "ModCode"
MONO_META_TEMPLATE = (
    "fileFormatVersion: 2\n"
    "guid: {guid}\n"
    "MonoImporter:\n"
    "  externalObjects: {{}}\n"
    "  serializedVersion: 2\n"
    "  defaultReferences: []\n"
    "  executionOrder: 0\n"
    "  icon: {{instanceID: 0}}\n"
    "  userData: \n"
    "  assetBundleName: \n"
    "  assetBundleVariant: \n"
)

ASSET_GUID_RE = re.compile(r"guid:\s*([0-9a-fA-F]{32})")
# 合并包里绝不携带脚本源码/已编译程序集（Toolkit 自己就有），避免重复导致 CS0263。
MERGE_SKIP_SUFFIXES = {".cs", ".dll"}


def class_name_of_file(cs_path: Path) -> str:
    """推断 .cs 的类名：文件名优先，其次取首个 class 声明。"""
    try:
        text = cs_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return cs_path.stem
    text = COMMENT_RE.sub("", text)  # 先剥注释，避免注释里的 "class Foo" 干扰
    declared = CLASS_DECL_RE.findall(text)
    if cs_path.stem in declared:
        return cs_path.stem
    return declared[0] if declared else cs_path.stem


def declared_types(cs_path: Path) -> set[tuple[str, bool]]:
    """取 .cs 里**顶层**声明的类型，返回 {(全限定名, 是否 partial)}。

    嵌套类型(如 AdaptModule 里的 Point)一律不计：不同外层类里同名嵌套类型是合法的，
    算进来会把它误判成重复定义进而误删真脚本。
    partial 标记必须保留 —— partial 与同名非 partial 共存是编译错误(CS0260)，
    但多个 partial 分片共存合法，分组后靠这个标记区分。
    """
    try:
        text = cs_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set()
    text = STRING_RE.sub('""', COMMENT_RE.sub("", text))
    ns_match = NS_DECL_RE.search(text)
    ns = ns_match.group(1) if ns_match else ""
    out: set[tuple[str, bool]] = set()
    depth = 0
    # 顶层类型的深度基准：块命名空间(namespace X {)下一层是 1，
    # 文件级命名空间(namespace X;)下一层是 0。ILSpy 反编译产物两种都会出现。
    base = 0
    for line in text.splitlines():
        m = TYPE_DECL_RE.match(line)
        if m and m.group(2) and depth == base:
            out.add((f"{ns}.{m.group(2)}" if ns else m.group(2), bool(m.group(1))))
        nm = NS_DECL_RE.match(line)
        if nm:
            # 只有 `namespace X;` 是文件级；`namespace X {` 与换行写 `{` 的都是块级
            base = depth + (0 if line.strip().endswith(";") else 1)
        depth += line.count("{") - line.count("}")
    return out


def is_asset_ripper_stub(cs_path: Path) -> bool:
    """识别 AssetRipper 生成的占位脚本（内容含 Dummy class 说明）。"""
    try:
        return "Dummy class" in cs_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def find_duplicate_types(root: Path) -> dict[str, tuple[list[Path], list[Path]]]:
    """扫描目录下同一类型被多处定义的情况。

    返回 {全限定名: (出现的全部文件, 其中非 partial 声明的文件)}。
    全是 partial 的跨文件分片属合法定义，不计入。
    """
    groups: dict[str, list[tuple[Path, bool]]] = {}
    for cs in sorted(Path(root).rglob("*.cs")):
        for fq, partial in declared_types(cs):
            groups.setdefault(fq, []).append((cs, partial))
    out: dict[str, tuple[list[Path], list[Path]]] = {}
    for fq, members in groups.items():
        files = sorted({p for p, _ in members})
        if len(files) < 2:
            continue
        solid = sorted({p for p, partial in members if not partial})
        if not solid:
            continue
        out[fq] = (files, solid)
    return out


def stub_conflicts(toolkit_scripts: Path) -> set[Path]:
    """Toolkit 里同一类既有真脚本又有 Dummy stub 时，返回该跳过的 stub 路径。

    Toolkit 若被 AssetRipper 处理过就会混进 stub，整拷时会把重复定义一起带给导出工程。
    """
    real: dict[str, Path] = {}
    stubs: dict[str, list[Path]] = {}
    for cs in Path(toolkit_scripts).rglob("*.cs"):
        for fq, _ in declared_types(cs):
            if is_asset_ripper_stub(cs):
                stubs.setdefault(fq, []).append(cs)
            else:
                real[fq] = cs
    out: set[Path] = set()
    for fq, paths in stubs.items():
        if fq in real:
            out.update(paths)
    return out


def asset_guid_of(file_path: Path) -> str:
    """读 .meta 里的 guid，读不到返回空串。"""
    meta = Path(str(file_path) + ".meta")
    if not meta.is_file():
        return ""
    m = re.search(r"^guid:\s*([0-9a-fA-F]+)", meta.read_text(encoding="utf-8", errors="ignore"), re.MULTILINE)
    return m.group(1).lower() if m else ""


def dedupe_conflicting_scripts(project_dir: Path, toolkit_root: Path, toolkit_guids: set[str], log) -> tuple[int, list[str]]:
    """删除同一类型被多处定义的 .cs，杜绝 CS0101。

    整拷 Toolkit 之后仍可能残留 AssetRipper stub(例如落在 Scripts/Assembly-CSharp
    这种按命名空间镜像的目录下)，与 Toolkit 副本同名同类 → 编译报重复定义。
    保留优先级：路径在 Toolkit 树里存在 → GUID 属于 Toolkit → 不在 Assembly-CSharp 下 → 路径短。
    """
    assets = Path(project_dir) / "Assets"
    if not assets.is_dir():
        return 0, []
    toolkit_root = Path(toolkit_root)
    stubs = {p for p in assets.rglob("*.cs") if is_asset_ripper_stub(p)}

    def score(p: Path) -> tuple:
        rel = p.relative_to(assets).as_posix()
        is_stub = 1 if p in stubs else 0
        in_toolkit = 0 if (toolkit_root / "Assets" / rel).is_file() else 1
        is_tk_guid = 0 if asset_guid_of(p) in toolkit_guids else 1
        under_asm = 1 if ("Assembly-CSharp" in rel) else 0
        return (is_stub, in_toolkit, is_tk_guid, under_asm, len(rel), rel)

    removed = 0
    conflicts: list[str] = []
    for fq, (files, solid) in find_duplicate_types(assets).items():
        # 只能删非 partial 的声明；有 partial 参与时 solid 全属多余，否则保留评分最优的一份
        drop = sorted(solid, key=score)
        if len(solid) == len(files):
            drop = drop[1:]
        if not drop:
            continue
        keep = sorted(set(files) - set(drop), key=score)[0]
        conflicts.append(fq)
        log(f"[免挂] [!] 类型重复定义 {fq} 保留 {keep.relative_to(assets).as_posix()}"
            f"删除 {len(drop)} 处")
        for p in drop:
            for f in (p, Path(str(p) + ".meta")):
                try:
                    if f.is_file():
                        f.unlink()
                except OSError:
                    pass
            removed += 1
    return removed, conflicts


def scan_script_meta(scripts_dir) -> dict[str, str]:
    """扫描一个脚本目录下的 .cs.meta，返回 {类名: guid}。"""
    scripts_dir = Path(scripts_dir)
    result: dict[str, str] = {}
    rank: dict[str, tuple[int, int]] = {}
    if not scripts_dir.is_dir():
        return result
    for meta in scripts_dir.rglob("*.cs.meta"):
        m = re.search(r"^guid:\s*([0-9a-fA-F]+)", meta.read_text(encoding="utf-8", errors="ignore"), re.MULTILINE)
        if not m:
            continue
        cs = meta.with_suffix("").with_suffix(".cs")
        name = class_name_of_file(cs)
        # 同名类可能混进 AssetRipper stub，优先记真脚本(非 stub、非 Assembly-CSharp)的 GUID
        cand = (0 if is_asset_ripper_stub(cs) else 1, 0 if "Assembly-CSharp" in cs.as_posix() else 1)
        if name in result and cand <= rank[name]:
            continue
        result[name] = m.group(1).lower()
        rank[name] = cand
    return result


def build_toolkit_guid_map(toolkit_root) -> dict[str, str]:
    """扫描 Toolkit 工程的 Assets/Scripts，返回 {类名: guid}。

    入参是工程根目录；若手上已是脚本目录，直接调 scan_script_meta()。
    """
    return scan_script_meta(Path(toolkit_root) / "Assets" / "Scripts")


def collect_monoscript_classes(pack_path: Path, platforms: tuple[str, ...] = PRE_BUILD_KEYS) -> set[str]:
    """取各平台 Build 里 MonoScript 类名的并集。

    单个平台缺失/损坏就跳过；一个都解析不到时抛 ValueError，避免免挂静默失效。
    """
    import UnityPy

    data = json.loads(Path(pack_path).read_text(encoding="utf-8-sig"))
    classes: set[str] = set()
    loaded_any = False
    for platform in platforms:
        value = data.get(platform)
        if not isinstance(value, str):
            continue
        try:
            raw = base64.b64decode(value, validate=False)
        except (ValueError, UnicodeError):
            continue
        if not raw:
            continue
        try:
            env = UnityPy.load(raw)
        except Exception:
            continue  # 该平台 bundle 损坏/无法解析则跳过，不强判
        loaded_any = True
        for obj in env.objects:
            if obj.type.name != "MonoScript":
                continue
            try:
                cls = getattr(obj.read(), "m_ClassName", "")
                if cls:
                    classes.add(cls)
            except Exception:
                continue
    # 不要求特定 bundle 魔数，只要“一个平台都没能加载”才判定失败，避免误伤异签名 bundle。
    if not loaded_any:
        raise ValueError(f"无法解析 .pack 中的任何 AssetBundle 检查字段 {', '.join(platforms)}")
    if not classes:
        raise ValueError("已读取 AssetBundle 但解析不到任何 MonoScript 类名")
    return classes


# 游戏自身程序集：MonoScript.m_AssemblyName 指向这些的是**原版类**（Toolkit 自带）
STOCK_ASSEMBLY_NAMES = {"assembly-csharp", "assembly-csharp-firstpass", "assembly-csharp-editor"}


def collect_monoscript_assemblies(pack_path: Path, platforms: tuple[str, ...] = PRE_BUILD_KEYS) -> dict[str, str]:
    """取包内 MonoScript 的 {类名: m_AssemblyName}。

    m_AssemblyName 才是区分"mod 自定义类"与"游戏原版类"的可靠依据：
      - 原版类 → Assembly-CSharp（SFS 游戏程序集，Toolkit 里有真源码）
      - mod 自定义类 → 作者自己的 dll（如 AssetsofIce.dll），只能由 CodeAssembly 提供
    不能拿"包内类名 - Toolkit 类名"来判定：Toolkit 版本不同会漏掉原版类，
    把它们误当成自定义类处理掉（原版脚本全挂的根因）。
    """
    import UnityPy

    data = json.loads(Path(pack_path).read_text(encoding="utf-8-sig"))
    result: dict[str, str] = {}
    for platform in platforms:
        value = data.get(platform)
        if not isinstance(value, str) or not value:
            continue
        try:
            raw = base64.b64decode(value, validate=False)
        except (ValueError, UnicodeError):
            continue
        if not raw:
            continue
        try:
            env = UnityPy.load(raw)
        except Exception:
            continue
        for obj in env.objects:
            if obj.type.name != "MonoScript":
                continue
            try:
                d = obj.read()
                cls = getattr(d, "m_ClassName", "") or ""
                asm = getattr(d, "m_AssemblyName", "") or ""
            except Exception:
                continue
            if cls and cls not in result:
                result[cls] = asm
    return result


def custom_monoscript_classes(pack_path: Path) -> set[str]:
    """包内真正由 mod 自带 dll 提供的类名（排除 Assembly-CSharp 里的原版类）。"""
    try:
        mapping = collect_monoscript_assemblies(pack_path)
    except Exception:
        return set()
    return {cls for cls, asm in mapping.items() if asm and asm.lower() not in STOCK_ASSEMBLY_NAMES}


def collect_monoscript_pathids(pack_path: Path, platforms: tuple[str, ...] = PRE_BUILD_KEYS) -> dict[int, tuple[str, str]]:
    """包内 MonoScript 的 {path_id: (类名, 程序集)}——**不依赖 AssetRipper stub** 的权威映射。

    bundle 里 MonoBehaviour.m_Script 是 PPtr(m_FileID=0, m_PathID=X)，X 就是这里的 key；
    MonoScript 上自带 m_ClassName / m_AssemblyName，足以决定该指向 Toolkit 真脚本还是 mod dll。
    有了它，即使 AssetRipper 一个 stub 都没生成，也能把脚本引用重写到正确目标。
    """
    import UnityPy

    data = json.loads(Path(pack_path).read_text(encoding="utf-8-sig"))
    out: dict[int, tuple[str, str]] = {}
    for platform in platforms:
        value = data.get(platform)
        if not isinstance(value, str) or not value:
            continue
        try:
            raw = base64.b64decode(value, validate=False)
        except (ValueError, UnicodeError):
            continue
        if not raw:
            continue
        try:
            env = UnityPy.load(raw)
        except Exception:
            continue
        for obj in env.objects:
            if obj.type.name != "MonoScript":
                continue
            try:
                d = obj.read()
                cls = getattr(d, "m_ClassName", "") or ""
                asm = getattr(d, "m_AssemblyName", "") or ""
            except Exception:
                continue
            if cls:
                out[int(obj.path_id)] = (cls, asm)
        if out:
            break
    return out


def _pptr_path_id(p) -> int:
    """把 UnityPy 的 PPtr / ComponentPair / dict 统一取成 int path_id。

    UnityPy 各版本返回形态不一：PPtr 对象、ComponentPair(component=PPtr)、
    或纯 dict。取不到就返回 0（等价于空引用），调用方按 0 处理即可。
    """
    if p is None:
        return 0
    if hasattr(p, "component"):            # m_Component 的元素是 ComponentPair
        return _pptr_path_id(p.component)
    for attr in ("m_PathID", "m_PathId", "path_id"):
        if hasattr(p, attr):
            try:
                return int(getattr(p, attr))
            except (TypeError, ValueError):
                return 0
    if isinstance(p, dict):
        for attr in ("m_PathID", "m_PathId", "path_id"):
            if attr in p:
                try:
                    return int(p[attr])
                except (TypeError, ValueError):
                    return 0
    return 0


# YAML 侧解析用的正则
_YAML_NODE_RE = re.compile(r"^--- !u!(\d+) &(-?\d+)\s*$")
_YAML_SCRIPT_RE = re.compile(r"m_Script:\s*\{[^}]*guid:\s*([0-9a-fA-F]+)")


def _yaml_field(nodes: dict, fid: int, key: str) -> str:
    """取 YAML 节点里的标量字段（如 m_Name / m_Father）。"""
    nd = nodes.get(fid)
    if not nd:
        return ""
    pat = re.compile(r"^\s*" + key + r":\s*(.*)$")
    for ln in nd["lines"]:
        m = pat.match(ln)
        if m:
            return m.group(1).strip()
    return ""


def _yaml_file_id(nodes: dict, fid: int, key: str) -> int:
    """取 YAML 节点里的单值 PPtr 字段（如 m_GameObject: {fileID: 123}）。"""
    v = _yaml_field(nodes, fid, key)
    m = re.search(r"fileID:\s*(-?\d+)", v)
    return int(m.group(1)) if m else 0


def _yaml_file_id_list(nodes: dict, fid: int, key: str) -> list[int]:
    """取 YAML 节点里的 PPtr 列表字段（如 m_Component / m_Children）。"""
    nd = nodes.get(fid)
    if not nd:
        return []
    out: list[int] = []
    started = False
    pat_head = re.compile(r"^\s*" + key + r":\s*$")
    pat_item = re.compile(r"^\s*-\s*(?:component:)?\s*\{fileID:\s*(-?\d+)\}")
    for ln in nd["lines"]:
        if not started:
            if pat_head.match(ln):
                started = True
            continue
        m = pat_item.match(ln)
        if m:
            out.append(int(m.group(1)))
            continue
        if ln.strip():
            break
    return out


def _parse_prefab_yaml(path: Path) -> dict[int, dict]:
    """把 .prefab 拆成 {fileID: {"type": int, "lines": [...]}}。"""
    nodes: dict[int, dict] = {}
    cur = None
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return nodes
    for ln in text.split("\n"):
        m = _YAML_NODE_RE.match(ln.rstrip("\r"))
        if m:
            cur = int(m.group(2))
            nodes[cur] = {"type": int(m.group(1)), "lines": []}
            continue
        if cur is not None:
            nodes[cur]["lines"].append(ln.rstrip("\r"))
    return nodes


def build_pack_prefab_script_map(
    pack_path: Path,
    platforms: tuple[str, ...] = PRE_BUILD_KEYS,
    log=None,
) -> tuple[dict[str, dict[tuple[int, int], tuple[str, str]]], dict[str, tuple[str, str]]]:
    """**权威映射**：从 .pack 自身算出「脚本位置 → 真实类名」。

    AssetRipper 1.1.x 对 SFS 这类包常常一个 MonoScript stub 都不生成，
    prefab 里 m_Script 的 GUID 是它凭空写的、工程里根本不存在。
    本函数绕开 AssetRipper，直接读包：

      prefab 部分（返回[0]）：
      - 以 Transform(m_Father==0) 找 prefab 根，根 GameObject 的 m_Name 即 prefab 名
      - 对整棵 Transform 树做先序遍历，序号 = 遍历序
      - 每个 GameObject 上按 m_Component 顺序数第几个 MonoBehaviour
      - 键 (遍历序, MonoBehaviour 序号) → (类名, 程序集)

      ScriptableObject 部分（返回[1]）：m_GameObject 为空的 MonoBehaviour 就是
      独立 .asset（贴图/PackData/资源类型等），按 m_Name 索引 → (类名, 程序集)。

    导出的 YAML 用同样规则能算出**完全相同的键**，两边一 join 就拿到
    guid→类名，无需任何 stub、无需猜字段。
    """
    import UnityPy

    if log is None:
        log = print
    data = json.loads(Path(pack_path).read_text(encoding="utf-8-sig"))
    for platform in platforms:
        value = data.get(platform)
        if not isinstance(value, str) or not value:
            continue
        try:
            raw = base64.b64decode(value, validate=False)
        except (ValueError, UnicodeError):
            continue
        if not raw:
            continue
        try:
            env = UnityPy.load(raw)
        except Exception:
            continue

        objs = {int(o.path_id): o for o in env.objects}
        scripts: dict[int, tuple[str, str]] = {}
        for o in env.objects:
            if o.type.name != "MonoScript":
                continue
            try:
                d = o.read()
                cls = getattr(d, "m_ClassName", "") or ""
                asm = getattr(d, "m_AssemblyName", "") or ""
            except Exception:
                continue
            if cls:
                scripts[int(o.path_id)] = (cls, asm)
        if not scripts:
            continue

        cache: dict[int, object] = {}

        def read(o):
            if o is None:
                return None
            key = int(o.path_id)
            if key in cache:
                return cache[key]
            try:
                v = o.read()
            except Exception:
                v = None
            cache[key] = v
            return v

        transforms: dict[int, object] = {}
        for o in env.objects:
            if o.type.name == "Transform":
                t = read(o)
                if t is not None:
                    transforms[int(o.path_id)] = t

        result: dict[str, dict[tuple[int, int], tuple[str, str]]] = {}
        for tid, t in transforms.items():
            if _pptr_path_id(getattr(t, "m_Father", None)) != 0:
                continue
            gobj = objs.get(_pptr_path_id(getattr(t, "m_GameObject", None)))
            gd = read(gobj)
            name = getattr(gd, "m_Name", "") or ""
            if not name:
                continue

            seq: dict[tuple[int, int], tuple[str, str]] = {}
            counter = [0]

            def walk(cur_tid: int) -> None:
                cur_t = transforms.get(cur_tid)
                if cur_t is None:
                    return
                idx = counter[0]
                counter[0] += 1
                g = objs.get(_pptr_path_id(getattr(cur_t, "m_GameObject", None)))
                gd2 = read(g)
                mb_i = 0
                for c in getattr(gd2, "m_Component", None) or []:
                    cid = _pptr_path_id(c)
                    co = objs.get(cid)
                    if co is None or co.type.name != "MonoBehaviour":
                        continue
                    md = read(co)
                    sp = _pptr_path_id(getattr(md, "m_Script", None))
                    seq[(idx, mb_i)] = scripts.get(sp, ("", ""))
                    mb_i += 1
                for ch in getattr(cur_t, "m_Children", None) or []:
                    walk(_pptr_path_id(ch))

            walk(tid)
            if seq:
                result.setdefault(name, {}).update(seq)

        # 独立的 ScriptableObject 资产（贴图 / PackData / 资源类型等）
        assets_map: dict[str, tuple[str, str]] = {}
        for o in env.objects:
            if o.type.name != "MonoBehaviour":
                continue
            d = read(o)
            if d is None or _pptr_path_id(getattr(d, "m_GameObject", None)) != 0:
                continue
            nm = getattr(d, "m_Name", "") or ""
            if not nm:
                continue
            sp = _pptr_path_id(getattr(d, "m_Script", None))
            cls = scripts.get(sp, ("", ""))
            if cls[0]:
                assets_map[nm] = cls

        if result or assets_map:
            log(f"[免挂] 已从 .pack 读出 {len(result)} 个 prefab 的脚本布局"
                f"(共 {sum(len(v) for v in result.values())} 处引用)"
                f"另有 {len(assets_map)} 个独立 ScriptableObject 资产")
            return result, assets_map
    return {}, {}


def resolve_export_script_guids(
    project_assets: Path,
    pack_map,
    log=None,
) -> dict[str, dict[str, object]]:
    """用 .pack 的脚本布局，把导出工程 prefab/.asset 里的空 GUID 还原成真实类名。

    pack_map 是 build_pack_prefab_script_map 的返回值 (prefab 布局, SO 资产表)。
    返回 {guid: {"class": 类名, "assembly": 程序集, "count": 出现次数}}；
    同一个 GUID 命中多个类名时记 conflict，调用方应保守跳过。
    """
    if log is None:
        log = print
    if not Path(project_assets).is_dir():
        return {}
    prefab_map, assets_map = pack_map if isinstance(pack_map, tuple) else (pack_map, {})
    if not prefab_map and not assets_map:
        return {}

    # 按 (prefab 名) 建索引；同名 prefab 可能有多个（导出工程里的 _0 副本）
    by_name: dict[str, list[dict]] = {}
    for name, seq in prefab_map.items():
        by_name.setdefault(name, []).append(seq)

    hits: dict[str, dict[str, object]] = {}

    def note(guid: str, cls: str, asm: str) -> None:
        if not cls:
            return
        rec = hits.get(guid)
        if rec is None:
            hits[guid] = {"class": cls, "assembly": asm, "count": 1, "classes": {cls: 1}}
            return
        rec["count"] = int(rec["count"]) + 1
        rec["classes"][cls] = rec["classes"].get(cls, 0) + 1
        if rec["class"] != cls:
            rec["class"] = "<冲突>"

    # --- B) 独立 ScriptableObject .asset：按资产名对 ---
    so_n = 0
    for asset in sorted(Path(project_assets).rglob("*.asset")):
        nodes = _parse_prefab_yaml(asset)
        if not nodes:
            continue
        for fid, nd in nodes.items():
            if nd["type"] != 114:
                continue
            mm = _YAML_SCRIPT_RE.search("\n".join(nd["lines"]))
            if not mm:
                continue
            name = _yaml_field(nodes, fid, "m_Name")
            if not name:
                name = re.sub(r"_\d+$", "", asset.stem)
            cls, asm = assets_map.get(name, ("", ""))
            if not cls:
                cls, asm = assets_map.get(re.sub(r"_\d+$", "", asset.stem), ("", ""))
            if cls:
                so_n += 1
                note(mm.group(1).lower(), cls, asm)
    if so_n:
        log(f"[免挂] 按资产名对齐 {so_n} 个 ScriptableObject .asset 的脚本类")
    paired = 0
    unpaired: list[str] = []
    for prefab in sorted(Path(project_assets).rglob("*.prefab")):
        nodes = _parse_prefab_yaml(prefab)
        if not nodes:
            continue
        roots = [f for f, nd in nodes.items()
                 if nd["type"] == 4 and _yaml_file_id(nodes, f, "m_Father") == 0]
        if not roots:
            continue
        root_name = _yaml_field(nodes, _yaml_file_id(nodes, roots[0], "m_GameObject"), "m_Name")

        seq: dict[tuple[int, int], str] = {}
        counter = [0]

        def walk(tid: int) -> None:
            idx = counter[0]
            counter[0] += 1
            gid = _yaml_file_id(nodes, tid, "m_GameObject")
            mb_i = 0
            for cid in _yaml_file_id_list(nodes, gid, "m_Component"):
                nd = nodes.get(cid)
                if not nd or nd["type"] != 114:
                    continue
                mm = _YAML_SCRIPT_RE.search("\n".join(nd["lines"]))
                if mm:
                    seq[(idx, mb_i)] = mm.group(1).lower()
                mb_i += 1
            for ch in _yaml_file_id_list(nodes, tid, "m_Children"):
                if ch in nodes:
                    walk(ch)

        walk(roots[0])

        cand = by_name.get(root_name) or by_name.get(prefab.stem) or []
        cand = [c for c in cand if len(c) == len(seq)] or cand
        if len(cand) != 1:
            unpaired.append(prefab.name)
            continue
        paired += 1
        for key, guid in seq.items():
            cls, asm = cand[0].get(key, ("", ""))
            note(guid, cls, asm)

    if paired:
        log(f"[免挂] 结构对齐 {paired} 个 prefab 还原出 {len(hits)} 个脚本 GUID 的真实类名")
    if unpaired:
        log(f"[免挂] [!] {len(unpaired)} 个 prefab 未能与 .pack 对齐 {unpaired[:5]}"
            f"{'...' if len(unpaired) > 5 else ''}")
    return hits


def rewrite_script_guids(text: str, stub_to_toolkit: dict[str, str]) -> tuple[str, int]:
    """把文本中命中 stub 的 m_Script GUID 替换为 Toolkit GUID，返回 (新文本, 替换次数)。"""
    changed = 0

    def do_replace(mm: re.Match) -> str:
        nonlocal changed
        new_guid = stub_to_toolkit.get(mm.group(2))
        if new_guid:
            changed += 1
            return mm.group(1) + new_guid + mm.group(3)
        return mm.group(0)

    return SCRIPT_REF_RE.sub(do_replace, text), changed


def collect_unresolved(text: str, stub_guid_to_class: dict[str, str], stub_to_toolkit: dict[str, str],
                       known_guids: set[str] | None = None) -> list[str]:
    """返回该文本里仍未解析(指向 stub 且未重写)的类名清单。

    入参是**已重写后的文本**，调用方负责传入，避免重复读盘。
    known_guids：工程里真实存在的资产 GUID。指向它们的引用已经修好了
    （典型是 mod 自带 dll：自定义类本来就指 dll，不需要重写），不该再报未解析。
    """
    unresolved: list[str] = []
    for mm in SCRIPT_REF_RE.finditer(text):
        guid = mm.group(2)
        if guid in stub_to_toolkit:
            continue
        if known_guids and guid in known_guids:
            continue
        cls = stub_guid_to_class.get(guid)
        if cls and cls not in unresolved:
            unresolved.append(cls)
    return unresolved


def verify_toolkit_self(toolkit_root, exclude_names: tuple[str, ...] = ()) -> dict[str, int]:
    """自检 Toolkit 本身：它自带的官方部件 prefab，能否命中它自己的脚本 GUID。

    这是"还原到打包前"能否成立的前提。Toolkit 脚本的 GUID 随版本固定，
    如果这款 Toolkit 自带的部件都对不上，说明它的版本/来源与 mod 作者用的
    不一致（或 .meta 被重新生成过），此时无论怎么对齐都不会成功。

    exclude_names：要跳过的部件目录名。跑第二遍时必须把上次合并进来的模组排除，
    否则它会把自己那份还没修好的 prefab 算进"Toolkit 自带部件"，报出吓人的假告警。
    """
    toolkit_root = Path(toolkit_root)
    guids = set(scan_script_meta(toolkit_root / "Assets" / "Scripts").values())
    parts_dir = toolkit_root / "Assets" / "Resources" / "Parts"
    if not guids or not parts_dir.is_dir():
        return {"prefabs": 0, "refs": 0, "missing": 0}
    skip = {n.lower() for n in exclude_names if n}
    result = {"prefabs": 0, "refs": 0, "missing": 0}
    for prefab in parts_dir.rglob("*.prefab"):
        if skip and any(part.lower() in skip for part in prefab.relative_to(parts_dir).parts):
            continue
        result["prefabs"] += 1
        try:
            text = prefab.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for mm in SCRIPT_REF_RE.finditer(text):
            result["refs"] += 1
            if mm.group(2).lower() not in guids:
                result["missing"] += 1
    return result


def extract_code_assembly(pack_path: Path, out_file: Path) -> Path | None:
    """把 pack 里的 CodeAssembly 解成 DLL 文件。

    pack 没带 / 不是 PE 文件都返回 None —— 那不是错误，只是这个 mod 没有自带程序集。
    """
    try:
        data = json.loads(Path(pack_path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    raw = data.get("CodeAssembly")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        blob = base64.b64decode(raw, validate=False)
    except (ValueError, UnicodeError):
        return None
    if blob[:2] != b"MZ":
        return None
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_bytes(blob)
    return out_file


# ---- 解包前扫描 -------------------------------------------------------------
# 硬性约定：解包(导入 mod .pack)前先扫一遍，先知道包里有什么（尤其自定义脚本/版本），
# 再选「保留 dll 当插件 / 反编译兜底 / 纯原版」路线，避免导入后才发现挂空、来回返工。

_REF_NAME_RE = re.compile(
    r"^(?:UnityEngine[\w.]*|Unity\.[\w.]+|Assembly-CSharp[\w-]*|System[\w.]*|"
    r"mscorlib|netstandard|Mono\.[\w.]*|Newtonsoft\.[\w.]*)$"
)


def _iter_printable_strings(blob: bytes, min_len: int = 4):
    """产出二进制里的可打印字符串：ASCII 与 UTF-16LE（.NET 元数据串常用后者）。"""
    for m in re.finditer(rb"[\x20-\x7E]{%d,}" % min_len, blob):
        yield m.group().decode("ascii", errors="ignore")
    for m in re.finditer(rb"(?:[\x20-\x7E]\x00){%d,}" % min_len, blob):
        yield m.group().decode("utf-16-le", errors="ignore")


def assembly_refs_from_bytes(blob: bytes) -> list[str]:
    """从程序集字节里提取它引用的托管程序集名（轻量扫描，不解析 PE 元数据表）。

    用途是和 Toolkit 的 Unity/SFS 版本比对：依赖对不上是脚本挂空、运行时 NRE 的高危信号。
    """
    hits: set[str] = set()
    for s in _iter_printable_strings(blob):
        s = s.strip()
        if len(s) >= 4 and _REF_NAME_RE.match(s):
            hits.add(s)
    return sorted(hits)


def dll_assembly_refs(dll_path: Path) -> list[str]:
    """读 dll 文件并提取它引用的托管程序集名。"""
    try:
        return assembly_refs_from_bytes(Path(dll_path).read_bytes())
    except OSError:
        return []


def toolkit_script_classes(toolkit_root) -> set[str]:
    """Toolkit 自带脚本里声明的类名集合，用来区分「mod 自定义类」与「SFS 原生类」。"""
    root = Path(toolkit_root)
    out: set[str] = set()
    scripts = root / "Assets" / "Scripts"
    if not scripts.is_dir():
        return out
    for cs in scripts.rglob("*.cs"):
        for fq, _ in declared_types(cs):
            out.add(fq.rsplit(".", 1)[-1])
    return out


def scan_pack(pack_path: Path, toolkit_root=None, log=None) -> dict:
    """解包前扫描包信息：先知道包里有什么，再决定走哪条路线。

    返回 {"pack","platforms","code_assembly","classes","custom_classes",
          "assembly_refs","route","warnings","error"}：
      platforms       各平台 Build 是否存在及解码后字节数（MacBuild/IOS_Build 常为 null）
      code_assembly   {"present","bytes","is_pe"}  —— 是否带自定义脚本 dll
      classes         包内全部 MonoScript 类名
      custom_classes  非 Toolkit 自带的自定义类名（未给 toolkit_root 时等于 classes）
      assembly_refs   dll 引用的托管程序集（版本兼容判断依据）
      route           "B_plugin_dll" 保留真 dll 当插件 / "stock_only" 纯原版 /
                      "manual" 有自定义类但没 dll，需人工处理
    """
    pack_path = Path(pack_path)
    platforms: dict[str, dict] = {}
    ca: dict = {"present": False, "bytes": 0, "is_pe": False}
    result: dict = {
        "pack": str(pack_path),
        "platforms": platforms,
        "code_assembly": ca,
        "classes": [],
        "custom_classes": [],
        "assembly_refs": [],
        "route": "stock_only",
        "warnings": [],
        "error": "",
    }
    warnings: list = result["warnings"]

    try:
        data = json.loads(pack_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        result["error"] = f"无法读取 .pack {exc}"
        return result

    # 1) 平台包是否齐全
    for key in PRE_BUILD_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value:
            try:
                size = len(base64.b64decode(value, validate=False))
            except (ValueError, UnicodeError):
                size = len(value)
            platforms[key] = {"present": True, "bytes": size}
        else:
            platforms[key] = {"present": False, "bytes": 0}
    missing = [k for k, v in platforms.items() if not v["present"]]
    if len(missing) == len(platforms):
        result["error"] = "未找到任何平台 AssetBundle"
        return result
    if missing:
        warnings.append(f"缺少平台包 {', '.join(missing)}（该平台将无法构建，通常不影响 Windows/Android）")

    # 2) 是否携带 CodeAssembly（自定义脚本）
    raw_ca = data.get("CodeAssembly")
    if isinstance(raw_ca, str) and raw_ca:
        try:
            blob = base64.b64decode(raw_ca, validate=False)
        except (ValueError, UnicodeError):
            blob = b""
        ca["present"] = True
        ca["bytes"] = len(blob)
        ca["is_pe"] = blob[:2] == b"MZ"
        if not ca["is_pe"]:
            warnings.append("CodeAssembly 不是有效 PE(dll) 文件")
        else:
            result["assembly_refs"] = assembly_refs_from_bytes(blob)

    # 3) 包内 MonoScript 类名里有哪些非 SFS 自带的自定义类
    try:
        classes: set[str] = collect_monoscript_classes(pack_path)
    except Exception as exc:  # UnityPy 缺失或 bundle 解析不了都只降级，不中断流程
        classes = set()
        warnings.append(f"未能解析 MonoScript 类名 {exc}")
    result["classes"] = sorted(classes)
    # 自定义类以 m_AssemblyName 判定（见 custom_monoscript_classes 的说明）；
    # 拿不到程序集信息时才退化成"包内类名 - Toolkit 类名"，并标注来源避免误判。
    own = custom_monoscript_classes(pack_path)
    if own:
        result["custom_classes"] = sorted(own)
        result["custom_source"] = "assembly_name"
    elif toolkit_root:
        native = toolkit_script_classes(toolkit_root)
        result["custom_classes"] = sorted(set(classes) - native)
        result["custom_source"] = "minus_toolkit(可能含原版类)"
    else:
        result["custom_classes"] = sorted(classes)
        result["custom_source"] = "all(未判定)"

    # 4) 建议路线
    custom: list = result["custom_classes"]
    if ca["present"] and ca["is_pe"]:
        result["route"] = "B_plugin_dll"
    elif custom:
        result["route"] = "manual"
        warnings.append("含自定义类但包内没有 CodeAssembly 自定义脚本无法自动提供 需人工处理")
    else:
        result["route"] = "stock_only"
    refs: list = result["assembly_refs"]
    if ca["is_pe"] and refs and "Assembly-CSharp" not in refs:
        warnings.append("dll 未引用 Assembly-CSharp 可能不依赖 SFS 游戏类型 请核对与 Toolkit 版本是否一致")

    if log:
        log("[扫描] 平台 " + ", ".join(f"{k}={'有' if v['present'] else '无'}" for k, v in platforms.items()))
        log(f"[扫描] CodeAssembly {'有 %d 字节' % ca['bytes'] if ca['present'] else '无'}")
        log(f"[扫描] 自定义类 {len(custom)} 个" + (f" {', '.join(custom[:10])}" if custom else ""))
        if refs:
            log(f"[扫描] dll 依赖 {', '.join(refs[:10])}")
        log(f"[扫描] 建议路线 {result['route']}")
        for w in warnings:
            log(f"[扫描] [!] {w}")
    return result


def find_ilspy() -> str | None:
    """定位 ilspycmd：先 PATH，再 dotnet global tool 的默认安装位置。"""
    found = shutil.which("ilspycmd") or shutil.which("ilspycmd.exe")
    if found:
        return found
    home = Path.home()
    for name in ("ilspycmd.exe", "ilspycmd"):
        candidate = home / ".dotnet" / "tools" / name
        if candidate.is_file():
            return str(candidate)
    return None


def decompile_assembly(dll: Path, out_dir: Path, log) -> Path | None:
    """调 ilspycmd 把 DLL 反编译成 .cs 工程目录，失败返回 None。"""
    tool = find_ilspy()
    if not tool:
        log("[自定义] [!] 未找到 ilspycmd 跳过自动反编译")
        return None
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            [tool, "-p", "-o", str(out_dir), str(dll)],
            capture_output=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"[自定义] [!] 反编译调用失败 {exc}")
        return None
    if not next(out_dir.rglob("*.cs"), None):
        tail = (proc.stderr or proc.stdout or b"").decode("utf-8", "ignore")[:200]
        log(f"[自定义] [!] 反编译没有产出 {tail}")
        return None
    return out_dir


def _guid_of_meta(meta_path) -> str:
    """读 .meta 文件首行的 guid（与 asset_guid_of 不同：这里直接读 .meta 文件本身）。"""
    p = Path(meta_path)
    if not p.is_file():
        return ""
    m = re.search(r"^guid:\s*([0-9a-fA-F]{32})", p.read_text(encoding="utf-8", errors="ignore"), re.MULTILINE)
    return m.group(1).lower() if m else ""


def _copy_tree(src: Path, dst: Path) -> int:
    """递归拷贝目录(仅文件)到 dst，返回拷贝文件数。"""
    n = 0
    dst.mkdir(parents=True, exist_ok=True)
    for p in sorted(Path(src).rglob("*")):
        if p.is_file():
            d = dst / p.relative_to(src)
            d.parent.mkdir(parents=True, exist_ok=True)
            d.write_bytes(p.read_bytes())
            n += 1
    return n


def _find_mod_assembly_dll(assets: Path, extracted_dll):
    """在导出工程 Plugins 里找出与包内 CodeAssembly 同源(字节一致)的 DLL 及其 meta guid。

    命中即说明 AssetRipper 把 mod 自有程序集当 Plugin 放进了工程，prefab 的 m_Script
    已正确指向它(FileID=类ID, guid=DLL.meta)。返回 (Path, guid) 或 (None, "")。
    """
    plugins = Path(assets) / "Plugins"
    if not plugins.is_dir() or not extracted_dll or not Path(extracted_dll).is_file():
        return None, ""
    blob = Path(extracted_dll).read_bytes()
    for dll in sorted(plugins.glob("*.dll")):
        if dll.read_bytes() == blob:
            g = _guid_of_meta(dll.with_suffix(".dll.meta"))
            if g:
                return dll, g
    return None, ""


def find_referenced_plugin_dlls(project_assets: Path, prefab_paths: list) -> list:
    """返回被给定 prefab 的 m_Script 引用、且存在于工程 Plugins 的 DLL 路径列表。"""
    assets = Path(project_assets)
    referenced: set[str] = set()
    HEX = "0123456789abcdefABCDEF"
    for pf in prefab_paths:
        try:
            txt = Path(pf).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in txt.splitlines():
            if "m_Script:" not in line:
                continue
            gi = line.find("guid:")
            if gi < 0:
                continue
            g = line[gi + 6:].lstrip().split(",")[0].strip()
            if len(g) == 32 and all(c in HEX for c in g):
                referenced.add(g.lower())
    out = []
    plugins = assets / "Plugins"
    if plugins.is_dir():
        for dll in sorted(plugins.glob("*.dll")):
            g = _guid_of_meta(dll.with_suffix(".dll.meta"))
            if g and g.lower() in referenced:
                out.append(dll)
    return out


# Unity 托管插件(.dll)的 .meta 模板。自己写一份是为了让 GUID 立刻可用：
# Unity 要等导入时才生成 .meta，而我们要在导入前就确认 prefab 能指到它。
PLUGIN_META_TEMPLATE = (
    "fileFormatVersion: 2\n"
    "guid: {guid}\n"
    "PluginImporter:\n"
    "  externalObjects: {{}}\n"
    "  serializedVersion: 2\n"
    "  iconMap: {{}}\n"
    "  executionOrder: {{}}\n"
    "  defineConstraints: []\n"
    "  isPreloaded: 0\n"
    "  isOverridable: 0\n"
    "  isExplicitlyReferenced: 0\n"
    "  validateReferences: 1\n"
    "  platformData:\n"
    "  - first:\n"
    "      : Any\n"
    "    second:\n"
    "      enabled: 0\n"
    "      settings: {{}}\n"
    "  userData: \n"
    "  assetBundleName: \n"
    "  assetBundleVariant: \n"
)


def _remove_conflicting_stubs(assets: Path, class_names, log=None) -> list[str]:
    """删掉声明了这些类、且确属 AssetRipper stub 的 .cs（连 .meta 一起）。

    只删 stub（内容含 "Dummy class"），绝不碰 Toolkit 真脚本或反编译出的真源码——
    否则 dll 里的同名类会和 stub 重复定义，编译直接 CS0101 失败。
    """
    wanted = {str(c).rsplit(".", 1)[-1] for c in class_names or ()}
    if not wanted:
        return []
    removed: list[str] = []
    for cs in sorted(Path(assets).rglob("*.cs")):
        if not is_asset_ripper_stub(cs):
            continue
        names = {fq.rsplit(".", 1)[-1] for fq, _ in declared_types(cs)}
        if not (names & wanted):
            continue
        meta = cs.with_name(cs.name + ".meta")
        try:
            cs.unlink()
            if meta.is_file():
                meta.unlink()
            removed.append(str(cs))
        except OSError:
            continue
    if removed and log:
        log(f"[自定义] 已移除 {len(removed)} 个与 dll 撞类的 stub（防 CS0101）")
    return removed


def install_code_assembly_as_plugin(project_dir: Path, pack_path: Path, class_names=None, log=None) -> dict:
    """方案 B（默认）：把包内真实 CodeAssembly.dll 当托管插件放进工程，零改 prefab。

    要点：
    - 落点 `Assets/Plugins/CodeAssembly.dll`，**必须保留原文件名**——MonoScript 的
      m_AssemblyName 就是它，改名会让 Unity 认不出里面的类。
    - 同时写一份 .meta（GUID 立即可用，便于导出前就确认引用能指到它）。
    - 顺手清掉会与 dll 撞类的 AssetRipper stub，避免 CS0101。

    返回 {"ok","dll","guid","removed_stubs","reason"}
    """
    result: dict = {"ok": False, "dll": "", "guid": "", "removed_stubs": [], "reason": ""}
    base = Path(project_dir)
    assets = base / "Assets"
    if not assets.is_dir():
        result["reason"] = "no_assets_dir"
        return result

    dll = extract_code_assembly(pack_path, base.parent / f"{base.name}_CodeAssembly.dll")
    if dll is None:
        result["reason"] = "no_code_assembly"
        return result

    plugins = assets / "Plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    target = plugins / "CodeAssembly.dll"
    blob = dll.read_bytes()
    if not (target.is_file() and target.read_bytes() == blob):
        target.write_bytes(blob)

    meta = target.with_name(target.name + ".meta")
    guid = _guid_of_meta(meta) if meta.is_file() else ""
    if not guid:
        guid = uuid.uuid4().hex
        meta.write_text(PLUGIN_META_TEMPLATE.format(guid=guid), encoding="utf-8")

    result.update({"ok": True, "dll": str(target), "guid": guid})
    result["removed_stubs"] = _remove_conflicting_stubs(assets, class_names, log)
    if log:
        log(f"[自定义] 方案B 已落位插件 {target.name} ({len(blob):,} 字节 guid {guid[:8]}…) "
            f"→ 自定义类由 dll 提供 无需改写 prefab")
    return result


def restore_custom_scripts(
    project_dir: Path,
    pack_path: Path,
    toolkit_classes: set[str],
    unresolved_classes: list[str],
    log,
) -> dict[str, object]:
    """用 pack 自带的 CodeAssembly 反编译出作者自定义脚本，接回导出工程。

    关键手法：新脚本的 .meta 直接复用原 stub 的 GUID，prefab 上指向旧 stub 的
    m_Script 因此自动命中，一个引用都不用改；stub 随之删除，避免重复定义。

    返回 {"ok", "dll", "decompiled", "classes", "files", "reason"}
    """
    result: dict[str, object] = {
        "ok": False, "dll": "", "decompiled": "", "classes": [], "files": 0, "reason": "",
    }
    base = Path(project_dir)
    assets = base / "Assets"
    if not assets.is_dir():
        return result

    dll = extract_code_assembly(pack_path, base.parent / f"{base.name}_CodeAssembly.dll")
    if dll is None:
        result["reason"] = "no_code_assembly"
        return result
    result["dll"] = str(dll)
    log(f"[自定义] 检出 CodeAssembly {dll.stat().st_size:,} 字节 已导出 {dll.name}")

    # 先看 AssetRipper 自己有没有把 mod 程序集当 Plugin 留在工程里
    mod_dll, mod_guid = _find_mod_assembly_dll(assets, dll)
    if mod_dll is None:
        # 方案 B（默认）：AssetRipper 没保留 dll，我们把它当托管插件落位，零改 prefab。
        # 注意这里只在"Plugins 里还没有同字节 dll"时才落，避免放两份同名程序集导致类型重复。
        # 先只落 dll，不动 stub：万一 dll 没被认成插件还要退回方案 A，
        # 那时得靠 stub 的 GUID 让 prefab 引用自动命中，提前删掉就找不回来了。
        plan_b = install_code_assembly_as_plugin(base, pack_path, None, log)
        result["plugin_dll"] = plan_b.get("dll", "")
        mod_dll, mod_guid = _find_mod_assembly_dll(assets, dll)

    # 情形1：dll 已在 Assets/Plugins 里、能被 prefab 的 m_Script 指到(FileID=类ID, guid=DLL.meta)。
    #        此时保留 DLL 即可解析；不要再写同名源码，否则与 DLL 重复定义 -> CS0101 编译失败。
    if mod_dll is not None:
        result["ok"] = True
        result["via"] = "dll"
        result["dll_guid"] = mod_guid
        result["classes"] = list(unresolved_classes)
        # 确认走 dll 路线后才清 stub——但**只清"真正由 mod dll 提供"的那些类**。
        # 原版类(m_AssemblyName=Assembly-CSharp)的 stub 必须留着：它们要被 align 重写到
        # Toolkit 真脚本，提前删掉 prefab 就指向不存在的 GUID，结果是
        # "自定义脚本挂上了、原版脚本全挂"。
        own: set[str] = set()
        try:
            own = custom_monoscript_classes(pack_path)
        except Exception:
            own = set()
        toolkit_names = set(toolkit_classes or ())
        removable = {c for c in own if c in set(unresolved_classes) and c not in toolkit_names}
        if own:
            log(f"[自定义] dll 自定义类 {len(removable)} 个 原版类 stub 保留不动")
        result["removed_stubs"] = _remove_conflicting_stubs(assets, removable, log)
        log(f"[自定义] 保留 mod 自有程序集 {mod_dll.name} (meta guid {mod_guid[:8]}…)")
        log(f"[自定义] prefab 的自定义脚本引用已指向该 DLL → 导出工程可直接解析，无需挂接")
        # 反编译只作「要改脚本时」的参考，成败都不影响本次结果（也不进最终包）
        src = decompile_assembly(dll, base.parent / f"{base.name}_Decompiled", log)
        if src is not None:
            result["decompiled"] = str(src)
            ref = base / "ModCode_Reference"
            copied = _copy_tree(src, ref)
            log(f"[自定义] 反编译源码另存为工程外 {ref.name}/ ({copied} 文件) 供阅读 / 改后重编译")
        return result

    # 情形2（兜底 = 方案 A）：dll 没能识别成插件，退回反编译源码接回工程。
    # 既然改走源码路线，先前落的 dll 必须撤掉——源码与 dll 里的同名类会重复定义(CS0101)。
    plugin_path = Path(str(result.get("plugin_dll", "")))
    if plugin_path.is_file():
        try:
            plugin_path.unlink()
            Path(str(plugin_path) + ".meta").unlink(missing_ok=True)
            result["plugin_dll"] = ""
            log(f"[自定义] 改走源码路线 已撤回落位的 dll {plugin_path.name}")
        except OSError:
            pass
    src = decompile_assembly(dll, base.parent / f"{base.name}_Decompiled", log)
    if src is None:
        result["reason"] = "decompile_unavailable"
        log(f"[自定义] [!] 已把 DLL 放在 {dll} 可用 ILSpy 或 dnSpy 手动反编译")
        return result
    result["decompiled"] = str(src)

    # 情形2：原逻辑 —— AssetRipper 把 mod 程序集导成了 stub(.cs Dummy) 没保留 DLL，
    #        prefab 指向 stub 的 GUID，这里写入真源码并复用 stub GUID，引用自动命中。
    # 反编译产物索引 {短类名: 文件}（同一文件可能含多个类型）
    class_to_file: dict[str, Path] = {}
    for cs in sorted(src.rglob("*.cs")):
        for fq, _ in declared_types(cs):
            class_to_file.setdefault(fq.rsplit(".", 1)[-1], cs)

    # 工程里现存的 {短类名: (guid, 文件)}，用来复用 stub 的 GUID
    existing_guid: dict[str, str] = {}
    existing_file: dict[str, Path] = {}
    for cs in assets.rglob("*.cs"):
        g = asset_guid_of(cs)
        for fq, _ in declared_types(cs):
            short = fq.rsplit(".", 1)[-1]
            if g:
                existing_guid.setdefault(short, g)
            existing_file.setdefault(short, cs)

    target_root = assets / "Scripts" / MOD_CODE_DIRNAME
    written = 0
    restored: list[str] = []
    for cs in sorted(set(class_to_file.values())):
        names = {fq.rsplit(".", 1)[-1] for fq, _ in declared_types(cs)}
        if names & set(toolkit_classes):
            continue  # Toolkit 里已有同名类，拷进去会 CS0101
        guid = next((existing_guid[n] for n in names if n in existing_guid), None)
        if guid is None:
            guid = uuid.uuid4().hex
        dest = target_root / cs.relative_to(src)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(cs.read_bytes())
        Path(str(dest) + ".meta").write_text(
            MONO_META_TEMPLATE.format(guid=guid), encoding="utf-8"
        )
        written += 1
        # GUID 已经转移给新文件，原 stub 必须删掉，否则重复定义
        for n in names:
            old = existing_file.get(n)
            if old is None or old == dest or not old.is_file():
                continue
            Path(str(old) + ".meta").unlink(missing_ok=True)
            old.unlink(missing_ok=True)
        for n in names:
            if n in unresolved_classes:
                restored.append(n)

    result["files"] = written
    result["classes"] = sorted(restored)
    result["ok"] = written > 0
    if written:
        log(f"[自定义] 已从 DLL 还原 {written} 个自定义脚本文件 → Assets/Scripts/{MOD_CODE_DIRNAME}")
        if restored:
            log(f"[自定义] 其中 {len(restored)} 个是 prefab 引用的类 {restored}")
    else:
        result["reason"] = "nothing_to_restore"
    return result


def align_scripts_to_toolkit(
    project_dir: Path,
    pack_path: Path,
    toolkit_root: Path,
    log=None,
) -> dict[str, object]:
    """对 AssetRipper 导出的工程执行脚本免挂对齐。"""
    if log is None:
        log = print
    report: dict[str, object] = {"ok": False}

    toolkit_map = build_toolkit_guid_map(toolkit_root)  # {类名: guid}
    if not toolkit_map:
        report["error"] = f"未在 Toolkit 中找到脚本 .meta {toolkit_root}"
        return report
    log(f"[免挂] Toolkit 脚本数 {len(toolkit_map)}")

    # 前提自检：Toolkit 自己有没有同名类重复(被 AssetRipper 处理过的 Toolkit 会混进 stub)
    toolkit_dups = find_duplicate_types(Path(toolkit_root) / "Assets" / "Scripts")
    if toolkit_dups:
        sample = [f"{fq}({len(v[0])}处)" for fq, v in list(toolkit_dups.items())[:5]]
        log(f"[免挂] [!!] Toolkit 自身有 {len(toolkit_dups)} 个重复类型定义 {sample}"
            f"{'...' if len(toolkit_dups) > 5 else ''}")
        log(f"[免挂] [!!] 说明这份 Toolkit 混入了 AssetRipper 占位 stub"
            f"会自动跳过这些 stub 但建议换成干净的 Toolkit 工程")

    # 前提自检：这份 Toolkit 自带的部件本身能不能命中自己的脚本
    selfcheck = verify_toolkit_self(toolkit_root, exclude_names=(mod_folder_name(pack_path),))
    if selfcheck["refs"]:
        log(f"[免挂] Toolkit 自检 自带部件 {selfcheck['prefabs']} 个"
            f"脚本引用命中 {selfcheck['refs'] - selfcheck['missing']}/{selfcheck['refs']}")
        if selfcheck["missing"]:
            log(f"[免挂] [!!] 这份 Toolkit 自带的部件就有 {selfcheck['missing']} 处脚本对不上"
                f"通常是 Toolkit 版本与 mod 作者用的不一致 或 .meta 被重新生成过"
                f"这种情况下免挂不会生效 请换成与 mod 作者相同的 Toolkit 版本")

    try:
        mono_classes = collect_monoscript_classes(pack_path)  # 四平台并集，为空即抛错
    except ImportError:
        report["error"] = "缺少 UnityPy 无法解析 MonoBehaviour 脚本类"
        return report
    except Exception as exc:
        report["error"] = f"解析 .pack 脚本类失败 {exc}"
        return report
    log(f"[免挂] 包内脚本类数(并集) {len(mono_classes)}")

    assets = project_dir / "Assets"
    unresolved_classes = sorted(c for c in mono_classes if c not in toolkit_map)

    # 0) 记录现有 stub：{stub_guid: 类名}
    stub_guid_to_class: dict[str, str] = {}
    # 注意：这一步必须在删 stub 之前，删掉之后就拿不到旧 GUID 与类名的对应关系了
    if assets.is_dir():
        for meta in assets.rglob("*.cs.meta"):
            m = re.search(r"^guid:\s*([0-9a-fA-F]+)", meta.read_text(encoding="utf-8", errors="ignore"), re.MULTILINE)
            if not m:
                continue
            cs = meta.with_suffix("").with_suffix(".cs")
            stub_guid_to_class[m.group(1).lower()] = class_name_of_file(cs)

    # 0.5) 权威映射：AssetRipper 常常一个 stub 都不生成，此时上面的表是空的，
    #      prefab 里的 m_Script GUID 全是它凭空写的、工程里查无此人。
    #      改从 .pack 自身做「Transform 遍历序 + 组件序号」结构对齐，直接拿到 guid→类名，
    #      不依赖 stub、不依赖猜字段。stub 存在时两者互为校验，冲突则以 .pack 为准。
    guid_to_class: dict[str, str] = dict(stub_guid_to_class)
    pack_map = ({}, {})
    pack_hits: dict[str, dict[str, object]] = {}
    if assets.is_dir():
        try:
            pack_map = build_pack_prefab_script_map(pack_path, log=log)
        except Exception as exc:  # 读包失败不能拖垮整条流水线
            if stub_guid_to_class:
                log(f"[免挂] 未能从 .pack 读取脚本布局（已有 stub 可用 忽略） {exc}")
            else:
                log(f"[免挂] [!] 未能从 .pack 读取脚本布局 {exc}")
            pack_map = ({}, {})
        if pack_map[0] or pack_map[1]:
            pack_hits = resolve_export_script_guids(assets, pack_map, log)
            for g, rec in pack_hits.items():
                cls = rec["class"]
                if not cls or cls == "<冲突>":
                    continue
                old = guid_to_class.get(g)
                if old and old != cls:
                    log(f"[免挂] [!] GUID {g} 在 stub 里是 {old} 在 .pack 里是 {cls}"
                        f"以 .pack 为准")
                guid_to_class[g] = cls
    if not stub_guid_to_class and pack_hits:
        log(f"[免挂] AssetRipper 未生成任何脚本 stub"
            f"已改用 .pack 结构对齐还原 {len(guid_to_class)} 个脚本 GUID")

    toolkit_scripts = toolkit_root / "Assets" / "Scripts"
    target_scripts = project_dir / "Assets" / "Scripts"

    # 1) 删掉将被 Toolkit 替换的 stub，避免同名类重复 → CS0101
    #    只删 GUID 与 Toolkit 不一致的（真正的 stub），重复运行时不会误删刚拷入的副本。
    #    扫描整个 Assets：AssetRipper 的 stub 也可能落在 Assets/MonoScript 等目录。
    removed_stub = 0
    if assets.is_dir():
        for meta in sorted(assets.rglob("*.cs.meta")):
            m = re.search(r"^guid:\s*([0-9a-fA-F]+)", meta.read_text(encoding="utf-8", errors="ignore"), re.MULTILINE)
            if not m:
                continue
            g = m.group(1).lower()
            clazz = class_name_of_file(meta.with_suffix("").with_suffix(".cs"))
            if clazz in toolkit_map and g != toolkit_map[clazz]:
                cs = meta.with_suffix("").with_suffix(".cs")
                try:
                    meta.unlink()
                    if cs.exists():
                        cs.unlink()
                    removed_stub += 1
                except OSError:
                    pass
    log(f"[免挂] 已删除 {removed_stub} 个将被替换的 AssetRipper stub 脚本")

    # 2) 整拷 Assets/Scripts，连基类/枚举/接口一起补齐 → 消 CS0246
    #    Toolkit 若混有 AssetRipper stub(同名类已有真脚本)则跳过，否则会把重复定义带给导出工程
    imported = 0
    skipped_stub_source = 0
    if toolkit_scripts.is_dir():
        skip_stub = stub_conflicts(toolkit_scripts)
        for cs in toolkit_scripts.rglob("*.cs"):
            if cs in skip_stub:
                skipped_stub_source += 1
                continue
            rel = cs.relative_to(toolkit_scripts)
            dest = target_scripts / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(cs.read_bytes())
            imported += 1
            meta = Path(str(cs) + ".meta")
            if meta.is_file():
                Path(str(dest) + ".meta").write_bytes(meta.read_bytes())
    else:
        log(f"[免挂] [!] 未找到 Toolkit 脚本目录 跳过导入 {toolkit_scripts}")
    log(f"[免挂] 已整拷 {imported} 个 Toolkit 脚本(含 .meta)")
    if skipped_stub_source:
        log(f"[免挂] 已跳过 {skipped_stub_source} 个 Toolkit 自带的 AssetRipper stub"
            f"这份 Toolkit 被 AssetRipper 处理过 建议清理后重试")

    # 2.5) 自定义脚本还原：pack 带 CodeAssembly 时反编译出源码接回工程，
    #      复用原 stub 的 GUID 所以 prefab 上一个引用都不用改。
    custom = restore_custom_scripts(
        project_dir, pack_path, set(toolkit_map), unresolved_classes, log
    )
    if custom["reason"] == "no_code_assembly" and unresolved_classes:
        log(f"[免挂] [!] 该 pack 未携带 CodeAssembly 这 {len(unresolved_classes)} 个自定义脚本"
            f"拿不到源码 只能保留空壳 stub {unresolved_classes[:8]}"
            f"{'...' if len(unresolved_classes) > 8 else ''}")

    # 2.6) 兜底去重：放最后一道，整拷残留的 stub 与反编译引入的重复都能一并清掉 → CS0101
    removed_dup, dup_classes = dedupe_conflicting_scripts(
        project_dir, toolkit_root, set(toolkit_map.values()), log
    )
    if removed_dup:
        log(f"[免挂] 已删除 {removed_dup} 个重复类型定义 涉及 {len(dup_classes)} 个类")

    # 3) 重写目标表。target_scripts 已是脚本目录，只能调 scan_script_meta；
    #    用 build_toolkit_guid_map 会再拼一层 Assets/Scripts，返回空表。
    imported_toolkit_guid = scan_script_meta(target_scripts)
    if not imported_toolkit_guid:
        report["error"] = "Toolkit 脚本已拷贝 但未能读出任何 .cs.meta GUID"
        return report

    stub_to_toolkit_pre: dict[str, str] = {}
    # 3.5) 自定义类的目标 GUID：dll 落位后，Unity 用 dll 的 .meta guid 表示里面的脚本。
    #      自定义类不在 Toolkit 源码里，只有指到 dll 才不会挂。
    custom_guid_target: dict[str, str] = {}
    plugins_dir = assets / "Plugins"
    if plugins_dir.is_dir():
        for dll in sorted(plugins_dir.glob("*.dll")):
            g = _guid_of_meta(dll.with_suffix(".dll.meta"))
            if g:
                custom_guid_target[dll.name] = g
    custom_targets = 0
    for g, rec in pack_hits.items():
        cls = rec["class"]
        if not cls or cls == "<冲突>" or cls in imported_toolkit_guid:
            continue
        asm = str(rec["assembly"] or "")
        if not asm or asm.lower() in STOCK_ASSEMBLY_NAMES:
            continue
        dll_guid = custom_guid_target.get(asm) or custom_guid_target.get(asm + ".dll")
        if dll_guid and dll_guid != g:
            stub_to_toolkit_pre[g] = dll_guid
            custom_targets += 1
    if custom_targets:
        log(f"[免挂] 已把 {custom_targets} 个自定义脚本 GUID 指到插件 DLL")

    # 4) 按类名建立 stub_guid -> toolkit_guid
    stub_to_toolkit: dict[str, str] = dict(stub_to_toolkit_pre)
    remapped_classes: set[str] = set()
    for stub_guid, class_name in guid_to_class.items():
        tk_guid = imported_toolkit_guid.get(class_name)
        if tk_guid and stub_guid != tk_guid:
            stub_to_toolkit[stub_guid] = tk_guid
            remapped_classes.add(class_name)
    log(f"[免挂] 已建立脚本 GUID 重写映射 {len(stub_to_toolkit)} 条")

    # 5) 重写 .prefab / .asset 的 m_Script（ScriptableObject 上的引用同样会挂）
    files = []
    if assets.is_dir():
        files = sorted(assets.rglob("*.prefab")) + sorted(assets.rglob("*.asset"))
    rewritten_count = 0
    total_rewrite = 0
    unresolved_prefab_names: list[str] = []
    # 注意：这里必须自己扫全部 .meta，不能用 index_asset_guids——那个为了做合并包
    # 会把 .cs / .dll 排除掉，而脚本引用指向的恰恰就是它们，用了会把已修好的全判成挂空。
    known_guids: set[str] = set()
    if assets.is_dir():
        for meta in assets.rglob("*.meta"):
            try:
                m = re.search(r"^guid:\s*([0-9a-fA-F]{32})",
                              meta.read_text(encoding="utf-8", errors="ignore"), re.MULTILINE)
            except OSError:
                continue
            if m:
                known_guids.add(m.group(1).lower())
    unresolved_guids: dict[str, dict[str, object]] = {}
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "m_Script:" not in text:
            continue
        new_text, n = rewrite_script_guids(text, stub_to_toolkit)
        if n:
            f.write_text(new_text, encoding="utf-8")
            rewritten_count += 1
            total_rewrite += n
        if collect_unresolved(new_text, guid_to_class, stub_to_toolkit, known_guids):
            unresolved_prefab_names.append(str(f.relative_to(project_dir)))
        # 终极自检：重写之后还指向工程里不存在的 GUID 的就是真挂空
        for mm in SCRIPT_REF_RE.finditer(new_text):
            g = mm.group(2).lower()
            if g in known_guids:
                continue
            rec = unresolved_guids.setdefault(
                g, {"class": guid_to_class.get(g, ""), "count": 0, "files": []})
            rec["count"] = int(rec["count"]) + 1
            rel = str(f.relative_to(project_dir))
            if len(rec["files"]) < 3 and rel not in rec["files"]:
                rec["files"].append(rel)
    log(f"[免挂] 已重写 {rewritten_count} 个 prefab/asset 共 {total_rewrite} 处脚本引用")
    if unresolved_guids:
        log(f"[免挂] [!!] 重写后仍有 {len(unresolved_guids)} 个脚本 GUID 在工程里找不到"
            f"共 {sum(int(r['count']) for r in unresolved_guids.values())} 处引用会挂空")
    # 自定义类不在 Toolkit 源码里是**正常的**（由 mod 的 dll 提供），不该报成问题
    custom_now = custom_monoscript_classes(pack_path)
    stock_unresolved = [c for c in unresolved_classes if c not in custom_now]
    if stock_unresolved:
        log(f"[免挂] [!] 以下原版类在 Toolkit 中找不到源码 无法接上 {stock_unresolved}")
    if unresolved_prefab_names:
        log(f"[免挂] [!] {len(unresolved_prefab_names)} 个文件仍存在未解析脚本引用 {unresolved_prefab_names[:8]}{'...' if len(unresolved_prefab_names) > 8 else ''}")

    report.update(
        {
            "ok": True,
            "toolkit_scripts": len(toolkit_map),
            "pack_classes": len(mono_classes),
            "remap_rules": len(stub_to_toolkit),
            "rewritten_prefabs": rewritten_count,
            "rewritten_refs": total_rewrite,
            "removed_stubs": removed_stub,
            "removed_duplicates": removed_dup,
            "duplicate_classes": dup_classes,
            "toolkit_duplicates": sorted(toolkit_dups),
            "skipped_stub_sources": skipped_stub_source,
            "toolkit_selfcheck": selfcheck,
            "custom_scripts": custom,
            "unresolved_classes": unresolved_classes,
            "unresolved_prefabs": unresolved_prefab_names,
            "unresolved_guids": unresolved_guids,
            "guid_to_class": guid_to_class,
            "pack_layout": len(pack_map[0]),
            "pack_so_assets": len(pack_map[1]),
        }
    )
    return report


def write_unresolved_report(out_path: Path, unresolved_guids: dict[str, dict[str, object]]) -> Path:
    """把仍然挂空的脚本 GUID 写成 UNRESOLVED_SCRIPTS.md，便于人工排查/求助。

    这是"闸门"的一半：工具拒绝带着挂空脚本合并进 Toolkit，同时把问题清单落到磁盘，
    避免只在日志里留一行、用户第二天就忘了到底是什么类没接上。
    """
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 未解析的脚本引用（Unresolved script references）",
        "",
        "下面的 GUID 在 prefab/asset 的 `m_Script` 里被引用，但导出工程里找不到对应的脚本资产。",
        "带着它们合并进 Toolkit，Unity 里会满屏 `Script attached to ... is missing`。",
        "",
        "| GUID | 类名 | 引用次数 | 出现文件（最多 3 个） |",
        "| --- | --- | --- | --- |",
    ]
    for g, rec in sorted(unresolved_guids.items(), key=lambda kv: -int(kv[1]["count"])):
        files = rec.get("files") or []
        lines.append(
            f"| `{g}` | {rec.get('class') or '(未知)'} | {rec['count']} | "
            + "<br>".join(f"`{x}`" for x in files)
            + " |"
        )
    lines += [
        "",
        "## 常见原因",
        "",
        "1. **Toolkit 版本与 mod 作者用的不一致** —— 最常见。换回同源版本后再导出。",
        "2. 这些类来自 mod 自带 dll，但 dll 没被识别/没写进 `Assets/Plugins`。",
        "3. 这份 Toolkit 的 `.meta` 被 Unity 重新生成过（GUID 全变）。",
        "",
        "## 处理建议",
        "",
        "- 先确认上表的类名是**原版类**还是**mod 自定义类**；",
        "- 原版类 → 换 Toolkit 版本；",
        "- 自定义类 → 确认 `Assets/Plugins` 里有对应的 dll 且文件名与 `m_AssemblyName` 一致。",
        "",
    ]
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def index_asset_guids(assets_dir: Path) -> dict[str, Path]:
    """扫描某 Assets 下所有文件的 .meta，返回 {guid: 资产文件}。"""
    result: dict[str, Path] = {}
    if not assets_dir.is_dir():
        return result
    for meta in assets_dir.rglob("*.meta"):
        try:
            m = re.search(r"^guid:\s*([0-9a-fA-F]{32})", meta.read_text(encoding="utf-8", errors="ignore"), re.MULTILINE)
        except OSError:
            continue
        if not m:
            continue
        asset = meta.with_suffix("")  # Foo.cs.meta -> Foo.cs, Foo.mat.meta -> Foo.mat
        if asset.is_file() and asset.suffix.lower() not in MERGE_SKIP_SUFFIXES:
            result[m.group(1).lower()] = asset
    return result


def collect_referenced_assets(assets_dir: Path, roots: list[Path], guid_map: dict[str, Path]) -> set[Path]:
    """从根部 prefab 出发，按 GUID 引用广度优先收集其依赖资产。"""
    needed: set[Path] = set()
    q: list[Path] = list(roots)
    while q:
        p = q.pop()
        if p in needed:
            continue
        needed.add(p)
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for g in set(ASSET_GUID_RE.findall(text)):
            target = guid_map.get(g.lower())
            if target is None or target in needed or target.suffix.lower() in MERGE_SKIP_SUFFIXES:
                continue
            q.append(target)
    return needed


def copy_with_meta(src: Path, dest: Path) -> int:
    """拷贝文件并连同其 .meta，返回拷贝的文件数(含.meta)。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    n = 1
    smeta = Path(str(src) + ".meta")
    if smeta.is_file():
        Path(str(dest) + ".meta").write_bytes(smeta.read_bytes())
        n += 1
    return n


# 模组资产归拢后的子文件夹（用户约定：<模组名>/Audio|Sticker|Prefab|Other）
MOD_AUDIO_DIRNAME = "Audio"
MOD_STICKER_DIRNAME = "Sticker"
MOD_PREFAB_DIRNAME = "Prefab"
MOD_OTHER_DIRNAME = "Other"
TEXTURE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tga", ".bmp", ".gif", ".psd", ".exr", ".hdr", ".dds"}
AUDIO_SUFFIXES = {".wav", ".mp3", ".ogg", ".aiff", ".flac"}
_UNSAFE_DIR_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def mod_folder_name(pack_path) -> str:
    """由 .pack 文件名得到安全的模组文件夹名。"""
    name = Path(pack_path).stem.strip() or "Mod"
    name = _UNSAFE_DIR_CHARS.sub("_", name).strip(" .")
    return name or "Mod"


def organize_mod_assets(project_assets: Path, mod_name: str, log=None) -> dict:
    """把模组自己带的资产归拢到 `<mod_name>/{Audio,Sticker,Prefab,Other}`。

    "模组自己带的" = 导出工程里 prefab 及其 GUID 依赖闭包（也就是 build_merge_package
    认定的新增内容）；Toolkit 自带/原版资产留在原地，不做搬动。

    两点必须注意：
    1. 移动时**连 .meta 一起搬**。Unity 靠 .meta 里的 GUID 维持引用，只搬文件会让
       Unity 重新生成 GUID，prefab 引用随即全断——这也是"贴图变黑板/丢音频"的常见根因。
    2. 只整理导出工程。合并进 Toolkit 时部件仍会归一化到 Resources/Parts，
       因此不影响构建出包。
    """
    assets = Path(project_assets)
    result: dict = {"moved": 0, "by_folder": {}, "skipped": 0, "error": ""}
    if not assets.is_dir():
        result["error"] = "no_assets_dir"
        return result

    guid_map = index_asset_guids(assets)
    prefabs = sorted(assets.rglob("*.prefab"))
    if not prefabs:
        result["error"] = "no_prefabs"
        return result
    needed = collect_referenced_assets(assets, prefabs, guid_map)

    # Pack Data：SFS 把音频以 byte[] 塞进 .asset，这种也要归到 Audio
    audio_assets: set[Path] = set()
    try:
        from sfs_project_exporter import _payload_candidates, classify_payload

        for f in needed:
            if f.suffix.lower() != ".asset":
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for data in _payload_candidates(text):
                if classify_payload(data).startswith("audio:"):
                    audio_assets.add(f)
                    break
    except Exception:
        pass  # 识别不出来就退回按扩展名分类，不影响整理

    def folder_for(p: Path) -> str:
        suf = p.suffix.lower()
        if suf == ".prefab":
            return MOD_PREFAB_DIRNAME
        if p in audio_assets or suf in AUDIO_SUFFIXES:
            return MOD_AUDIO_DIRNAME
        if suf in TEXTURE_SUFFIXES:
            return MOD_STICKER_DIRNAME
        return MOD_OTHER_DIRNAME

    mod_root = assets / mod_name
    for p in sorted(needed):
        if not p.is_file():
            continue
        try:
            p.relative_to(mod_root)  # 已在目标结构里 → 幂等跳过
            result["skipped"] += 1
            continue
        except ValueError:
            pass
        folder = folder_for(p)
        dest = mod_root / folder / p.name
        if dest == p:
            continue
        index = 2
        while dest.exists():  # 重名不覆盖，加序号
            dest = mod_root / folder / f"{p.stem}_{index}{p.suffix}"
            index += 1
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(dest))
        meta = Path(str(p) + ".meta")
        if meta.is_file():
            shutil.move(str(meta), str(dest) + ".meta")
        result["moved"] += 1
        result["by_folder"][folder] = result["by_folder"].get(folder, 0) + 1

    if log:
        detail = ", ".join(f"{k} {v}" for k, v in sorted(result["by_folder"].items())) or "无"
        log(f"[整理] 模组资产已归拢到 Assets/{mod_name}/ {detail}")
    return result


def _merge_copy_custom_scripts(project_assets: Path, prefabs: list, package_assets: Path, log=None) -> dict:
    """合并包必须把 mod 自有脚本带进去，否则贴进 Toolkit 后自定义脚本引用悬空。

    情形1：prefab 的 m_Script 指向 mod 自有程序集 DLL(在 Assets/Plugins)，复制 DLL + .meta。
    情形2：反编译源码落在 Assets/Scripts/ModCode，整体复制 .cs + .meta。
    这两类在依赖收集阶段被 MERGE_SKIP_SUFFIXES 跳过，必须在此显式补上
    —— 这正是之前『没挂上』的根因之一(合并包漏带了程序集)。
    Toolkit 自带脚本不在此处理(已在 Toolkit 内，且依赖收集阶段已被排除)。
    """
    if log is None:
        log = print
    stats: dict[str, object] = {"dll": 0, "cs": 0, "assets": []}
    # 情形1：被 prefab 引用的 mod DLL（仅拷被引用者，避免顺手带无关程序集）
    for dll in find_referenced_plugin_dlls(project_assets, prefabs):
        meta = dll.with_suffix(".dll.meta")
        dest = package_assets / "Plugins" / dll.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dll, dest)
        stats["assets"].append(dest)
        if meta.is_file():
            Path(str(dest) + ".meta").write_bytes(meta.read_bytes())
        stats["dll"] += 1
    # 情形2：ModCode 自定义源码（restore_custom_scripts 已剔除与 Toolkit 重名的类，安全）
    modcode = Path(project_assets) / "Scripts" / MOD_CODE_DIRNAME
    if modcode.is_dir():
        for cs in sorted(modcode.rglob("*.cs")):
            rel = cs.relative_to(project_assets)
            dest = package_assets / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cs, dest)
            stats["assets"].append(dest)
            smeta = Path(str(cs) + ".meta")
            if smeta.is_file():
                Path(str(dest) + ".meta").write_bytes(smeta.read_bytes())
            stats["cs"] += 1
    return stats


def _parts_subfolder_name(pack_path: Path) -> str:
    """新增部件归入的子目录名：取 .pack 文件名，去掉文件系统非法字符。

    直接塞进 Resources/Parts 会把玩家导入的部件和 Toolkit 自带部件混在一起，
    建一层以模组命名的子目录，方便整包管理、定位与删除。
    """
    stem = Path(pack_path).stem if pack_path else ""
    stem = re.sub(r'[<>:"/\\|?*]', "_", stem).strip().strip(". ")
    return stem or "Imported"


# 材质里着色器引用，形如 m_Shader: {fileID: 4800000, guid: xxxx..., type: 3}
SHADER_REF_RE = re.compile(
    r"(m_Shader:\s*\{\s*fileID:\s*\d+\s*,\s*guid:\s*)([0-9a-fA-F]{32})(\s*,\s*type:\s*3\s*\})",
    re.IGNORECASE,
)
# .shader 文件里声明的着色器名，形如 Shader "SFS/Weird"
SHADER_NAME_RE = re.compile(r'^\s*Shader\s+"([^"]+)"', re.MULTILINE)
# AssetRipper 反编译不了着色器时写下的占位标记
DUMMY_SHADER_MARK = "DummyShaderTextExporter"
# 真着色器一般几 KB；超过这个体积就不当占位版处理，避免误伤 mod 自制着色器
STUB_MAX_BYTES = 8192


def _read_text(path: Path) -> str:
    """读文本资产。Unity 导出的 .shader/.meta 常带 UTF-8 BOM，这里统一去掉，
    否则 `^\\s*Shader "SFS/xxx"` 这类行首正则会全部失配（真着色器被误判成"没找到真身"）。"""
    return path.read_text(encoding="utf-8", errors="ignore").lstrip("\ufeff")


def _shader_declared_name(shader: Path) -> str:
    """读 .shader 里声明的着色器名（如 SFS/Weird）。"""
    try:
        m = SHADER_NAME_RE.search(_read_text(shader))
    except OSError:
        return ""
    return m.group(1) if m else ""


def _meta_guid(meta: Path) -> str:
    """读 .meta 里的 guid（小写）。"""
    try:
        m = re.search(r"^guid:\s*([0-9a-fA-F]{32})", _read_text(meta), re.MULTILINE)
    except OSError:
        return ""
    return m.group(1).lower() if m else ""


def _is_stub_shader(text: str) -> bool:
    """判断一份 .shader 是不是 AssetRipper 的占位空壳。

    判定必须保守——认错了就会把 mod 自制的真着色器删掉。两条判据：
    1. 带 `//DummyShaderTextExporter` 标记（AssetRipper 会原样写下，铁证）；
    2. 老版 AssetRipper 不写标记，但会生成一模一样的 Standard 表面着色器样板
       （`#pragma surface surf Standard` + `SurfaceOutputStandard` 的 surf 函数），
       且体积小得离谱。再叠加"必须是 SFS/ 开头"这一条，把 mod 自制着色器排除掉。
    """
    if DUMMY_SHADER_MARK in text:
        return True
    if len(text) > STUB_MAX_BYTES:
        return False
    return (
        "#pragma surface surf Standard" in text
        and "SurfaceOutputStandard" in text
        and SHADER_NAME_RE.search(text) is not None
        and 'Shader "SFS/' in text
    )


def fix_stub_shaders(
    project_assets: Path,
    toolkit_root: Path,
    log=None,
    mode: str = "copy",
    backup_dir: Path | str | None = None,
) -> dict[str, object]:
    """把工程里的 AssetRipper 空壳着色器换成 Toolkit 真着色器。

    AssetRipper 反编译不了 SFS 的自定义着色器，会写成带 DummyShaderTextExporter
    标记的不透明 Standard 占位版 —— 零件因此渲成一整块黑板（**不会报错**）。
    按 .shader 里声明的 Shader 名匹配 Toolkit 真着色器，两种模式：

    - mode="copy"：把空壳文件的**内容**换成真着色器源码（保留文件名与 GUID），
      材质一行都不用改，工程自身即可正确渲染 —— **导出工程用这个**。
    - mode="remap"：把材质 m_Shader 的 GUID 重指向 Toolkit 真着色器并**删掉重复文件**，
      避免往 Toolkit 里塞进两个同名 Shader —— **合并包用这个**。

    判定为“空壳”的条件（见 _is_stub_shader，保守优先）：声明的 Shader 名能在
    Toolkit 里找到同名真身、GUID 与 Toolkit 不同，且自身是占位版（带
    DummyShaderTextExporter 标记，或是 AssetRipper 那套 Standard 表面着色器样板）。
    已修过的文件再跑一遍是幂等的。

    backup_dir 给定时，remap 模式下被删的空壳会先挪进该目录（保留相对路径）。
    """
    if log is None:
        log = print
    result: dict[str, object] = {
        "stubs": 0,
        "fixed": 0,
        "refs": 0,
        "deleted": 0,
        "unmatched": [],
        "map": {},  # 空壳 guid -> Toolkit 真 guid
    }
    project_assets = Path(project_assets)
    toolkit_assets = Path(toolkit_root) / "Assets"
    if not project_assets.is_dir() or not toolkit_assets.is_dir():
        return result
    backup_dir = Path(backup_dir) if backup_dir else None

    # 1) Toolkit 真着色器：声明名 -> (guid, 源文件)
    # 分两桶收集：真身优先，空壳只当兜底。清理 Toolkit 自身时两棵树是同一棵，
    # 若混在一桶里按遍历顺序覆盖，残留的空壳会把真身顶掉，材质反而被指到空壳上。
    real: dict[str, tuple[str, Path]] = {}
    real_stub: dict[str, tuple[str, Path]] = {}

    for meta in toolkit_assets.rglob("*.shader.meta"):
        shader = meta.with_suffix("").with_suffix(".shader")
        if not shader.is_file():
            continue
        try:
            text = _read_text(shader)
        except OSError:
            continue
        name = _shader_declared_name(shader)
        guid = _meta_guid(meta)
        if not name or not guid:
            continue
        # 同名真身已收录时，别让后来的空壳把它顶掉
        if _is_stub_shader(text):
            real_stub.setdefault(name, (guid, shader))
        elif name not in real:
            real[name] = (guid, shader)

    def _lookup(name: str) -> tuple[str, Path] | None:
        return real.get(name) or real_stub.get(name)

    # 2) 工程里的空壳着色器
    stubs: list[tuple[str, Path, str]] = []  # (声明名, .shader 文件, stub guid)
    for meta in project_assets.rglob("*.shader.meta"):
        shader = meta.with_suffix("").with_suffix(".shader")
        if not shader.is_file():
            continue
        try:
            text = _read_text(shader)
        except OSError:
            continue
        name = _shader_declared_name(shader)
        guid = _meta_guid(meta)
        if not name or not guid:
            continue
        hit = _lookup(name)
        if not hit:
            # Toolkit 里没同名真身 —— 多半是 mod 自制着色器，原样保留
            if DUMMY_SHADER_MARK in text:
                result["unmatched"].append(name)
            continue
        real_guid = hit[0]
        if real_guid == guid:
            continue  # 本身就是 Toolkit 那份，无需处理
        if not _is_stub_shader(text):
            # 有内容的真着色器 —— copy 模式下绝不能覆盖。
            # remap 模式另当别论：只要它和 Toolkit 那份**逐字节等价**，就说明是
            # 同一份着色器的另一份拷贝（例如上一轮 copy 模式刚把它换成真源码），
            # 留着会在 Toolkit 里出现两个同名 Shader，必须去重。
            if not (mode == "remap" and _assets_equivalent(shader, hit[1])):
                continue
        result["stubs"] += 1
        stubs.append((name, shader, guid, hit))

    if not stubs:
        return result

    result["map"] = {guid: hit[0] for _, _, guid, hit in stubs}

    if mode == "remap":
        # 3a) 材质 GUID 重指向 Toolkit 真着色器
        stub_to_real = {guid: hit[0] for _, _, guid, hit in stubs}

        def repl(mm: re.Match) -> str:
            new = stub_to_real.get(mm.group(2).lower())
            if not new:
                return mm.group(0)
            result["refs"] += 1
            return mm.group(1) + new + mm.group(3)

        for pattern in ("*.mat", "*.prefab", "*.asset", "*.unity"):
            for f in project_assets.rglob(pattern):
                try:
                    text = f.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if "m_Shader:" not in text:
                    continue
                new_text = SHADER_REF_RE.sub(repl, text)
                if new_text != text:
                    f.write_text(new_text, encoding="utf-8")
                    # 顺手把内部 m_Name 改成与文件名一致，消掉 Odin 的
                    # "main object name should match the asset filename" 警告
                    if f.suffix.lower() in (".mat", ".asset", ".prefab"):
                        sync_asset_name(f)
        # 4) 删掉空壳，别把占位版带进 Toolkit
        for name, shader, guid, hit in stubs:
            if backup_dir:
                try:
                    rel = shader.relative_to(project_assets)
                except ValueError:
                    rel = Path(shader.name)
                for p in (shader, Path(str(shader) + ".meta")):
                    if not p.is_file():
                        continue
                    dst = backup_dir / rel.parent / (rel.name if p is shader else rel.name + ".meta")
                    try:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        if dst.exists():
                            dst.unlink()
                        shutil.copy2(p, dst)
                    except OSError:
                        pass
            for p in (shader, Path(str(shader) + ".meta")):
                try:
                    if p.is_file():
                        p.unlink()
                        result["deleted"] += 1
                except OSError:
                    pass
    else:
        # 3b) 就地换成真着色器源码，保留文件名与 GUID
        for name, shader, guid, hit in stubs:
            src = hit[1]
            try:
                shader.write_bytes(src.read_bytes())
                result["fixed"] += 1
            except OSError:
                continue

    result["fixed"] = result["fixed"] or len(stubs)
    extra = ""
    if mode == "remap":
        extra = " 重写材质引用 {} 处 删除空壳文件 {} 个".format(result["refs"], result["deleted"])
    log("[着色器] 空壳 {} 个 已换成 Toolkit 真着色器 {} 个{}".format(result["stubs"], len(stubs), extra))
    if result["unmatched"]:
        log(f"[着色器] [!] Toolkit 里找不到同名真着色器 {sorted(set(result['unmatched']))}")
    return result


# 资产内部的对象名（m_Name: xxx）。第一个捕获组是**行首缩进**，替换时必须原样保留：
# Unity YAML 里 m_Name 属于 `Material:` / `GameObject:` 这个映射，缩进一丢，Unity 就
# 读不到它 → 主对象名为空 → 材质/资产损坏（Odin 报 "Material {} has a missing shader"）。
M_NAME_RE = re.compile(r"^([ \t]*)m_Name:[ \t]*(.*)$", re.MULTILINE)


def sync_asset_name(asset: Path) -> bool:
    """把资产内部的 m_Name 改成与文件名一致，并保证它仍然带 YAML 缩进。

    改名保留的副本（如 `Engine Olders 1v_Weird.mat`）内部还写着原来的
    `m_Name: Weird`，Odin 就会一直刷 "The main object name should match the
    asset filename"。全文件恰好一处 m_Name 时才动手，避免误改 prefab 子物体名。

    **顶格（无缩进）的 m_Name 一定有问题**，必须补回缩进：Unity 的 YAML 里
    m_Name 属于 `Material:` / `GameObject:` 这个映射，一旦顶格，Unity 就读不到它，
    主对象名变空 → 整个材质损坏（Odin 报 "Material {} has a missing shader"、
    Renderer 绑不上材质导致 `RenderSortingModule.SetDepth` NRE）。所以这种情况
    即使名字已经对了也要改回缩进形式。
    """
    asset = Path(asset)
    try:
        text = _read_text(asset)
    except OSError:
        return False
    hits = M_NAME_RE.findall(text)
    if len(hits) != 1:
        return False
    indent, value = hits[0][0], hits[0][1].strip()
    if value == asset.stem and indent:
        return False  # 名字已对且缩进正常，不动
    indent = indent or "  "  # 顶格的补回 Unity 惯用的两空格
    new_text = M_NAME_RE.sub(lambda m: f"{indent}m_Name: {asset.stem}", text, count=1)
    try:
        asset.write_text(new_text, encoding="utf-8")
    except OSError:
        return False
    return True


def fix_asset_name_mismatches(assets_dir: Path, log=None) -> int:
    """把资产内部 m_Name 与文件名对齐（仅对全文件恰好一处 m_Name 的文件动手）。

    早期导入流程对同名资源加了前缀改名（如 `Engine Olders 1v_Weird.mat`），
    但没改内部 m_Name，于是 Odin 一直刷 "The main object name should match the
    asset filename"。返回修正了多少个文件。
    """
    if log is None:
        log = print
    assets_dir = Path(assets_dir)
    n = 0
    for suf in (".mat", ".asset", ".prefab"):
        for f in assets_dir.rglob("*" + suf):
            try:
                if sync_asset_name(f):
                    n += 1
            except OSError:
                continue
    if n:
        log(f"[命名] 已把 {n} 个资产的 m_Name 对齐到文件名")
    return n


def repair_toolkit_shaders(toolkit_root: Path, log=None, backup: bool = True) -> dict[str, object]:
    """清理 Toolkit 里**已经存在**的 AssetRipper 空壳着色器（历史遗留修复）。

    早期版本的导入流程没做着色器对齐，把 `Shader/SFS_*.shader` 这类占位版连同
    材质一起写进了 Toolkit；材质 m_Shader 指向它们 → 零件渲成黑板，而且
    Unity 不会报任何错。这里按 Shader 名把引用重指向 `Materials/Shaders/` 下的
    真身，再删掉空壳（默认先备份到 `<Toolkit>/_PackToolBackup/<时间>_stubshaders/`）。
    同时把导出流程改名留下的 m_Name 与文件名不一致也一并修掉。
    """
    import time

    if log is None:
        log = print
    toolkit_root = Path(toolkit_root)
    backup_dir = None
    if backup:
        backup_dir = toolkit_root / "_PackToolBackup" / (time.strftime("%Y%m%d_%H%M%S") + "_stubshaders")
    rep = fix_stub_shaders(
        toolkit_root / "Assets", toolkit_root, log=log, mode="remap", backup_dir=backup_dir
    )
    rep["names_fixed"] = fix_asset_name_mismatches(toolkit_root / "Assets", log=log)
    rep["backup_dir"] = str(backup_dir) if backup_dir else ""
    return rep


# 资产文件里的 guid 引用（{fileID:.., guid:.., type:..} 或裸的 guid: 行）
GUID_FIELD_RE = re.compile(r"guid:\s*([0-9a-fA-F]{32})")
# 参与引用重写的文本资产后缀
REWRITE_SUFFIXES = {".prefab", ".mat", ".asset", ".unity", ".controller", ".anim", ".playable"}
# Unity 内置空引用占位 GUID（如内置着色器 Sprites/Default 用 fileID 456.. + 此 GUID 存）。
# 它不是工程内资产、也不需要 .meta，引用它属正常 —— 扫描时一律视为"已解析"，避免误报悬空。
UNITY_BUILTIN_NULL_GUIDS = {"0000000000000000f000000000000000"}


def _norm_asset_text(text: str) -> str:
    """把 guid 值统一打码、去掉空白差异，用于判断两份资产是不是「同一个东西的副本」。

    注意必须连**内联引用**里的 guid 一起打码：AssetRipper 导出的那份副本，
    与 Toolkit 里原版的差别恰恰就在 `{fileID: 2800000, guid: xxx, type: 3}`
    这种内联引用上，而不是独立的 guid 行（那是 .meta 才有的）。
    """
    text = GUID_FIELD_RE.sub("guid: <G>", text.replace("\r\n", "\n"))
    out = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("guid: <G>"):
            continue
        out.append(stripped)
    return "\n".join(out)


def _assets_equivalent(a: Path, b: Path) -> bool:
    """两份资产是否等价：二进制直接比字节；文本比"去 guid 去空白"后的内容。"""
    try:
        raw_a = a.read_bytes()
        raw_b = b.read_bytes()
    except OSError:
        return False
    if raw_a == raw_b:
        return True
    try:
        text_a = raw_a.decode("utf-8")
        text_b = raw_b.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return _norm_asset_text(text_a) == _norm_asset_text(text_b)


def count_dangling_refs(text: str, known_guids: set) -> int:
    """数一份资产文本里有多少处 guid 引用在 known_guids 里找不到（即悬空引用）。"""
    return sum(1 for g in GUID_FIELD_RE.findall(text)
               if g.lower() not in known_guids and g.lower() not in UNITY_BUILTIN_NULL_GUIDS)


def remap_toolkit_duplicates(
    package_assets: Path,
    toolkit_assets: Path,
    log=None,
    rename_tag: str = "mod",
) -> dict[str, object]:
    """把包内"与 Toolkit 同路径"的原版资源重定向到 Toolkit 已有的那一份。

    AssetRipper 导出的是一个**平行 GUID 世界**：mod 复用的 SFS 原版贴图 / 材质 /
    音效 / 配置资源，AssetRipper 会给每份都单独导出一个副本并重新生成 GUID，
    副本内部又引用平行世界里的其它 GUID。直接把这种包贴进 Toolkit 会踩两个坑：

    1. 同名文件撞上 Toolkit 已有资源，按"不覆盖"策略被跳过，prefab 仍指着包内
       那份 GUID → 引用悬空（Odin 报 missing，渲染脚本取不到材质直接 NRE）；
    2. 就算强行拷进去，副本内部的引用仍指向 Toolkit 里不存在的 GUID，照样悬空。

    所以这里以 `Assets` 下的**相对路径**作为资产身份：凡是 Toolkit 里已有同路径
    资产，就把包内对它的引用全部改写成 Toolkit 那份的 GUID，并删掉包内副本。
    只有内容和 Toolkit 不一致（说明 mod 确实改过它）时才保留副本，并改名加前缀，
    既不丢 mod 的改动，也不跟 Toolkit 的同名文件撞车。
    """
    if log is None:
        log = print
    result: dict[str, object] = {
        "dupes": 0,
        "redirected": 0,
        "kept_diff": [],
        "refs": 0,
        "removed": 0,
        "empty": False,
    }
    package_assets = Path(package_assets)
    toolkit_assets = Path(toolkit_assets)
    if not package_assets.is_dir() or not toolkit_assets.is_dir():
        result["empty"] = True
        return result

    # 1) Toolkit 侧索引：相对路径(小写) -> (guid, 资产文件)
    tk_by_rel: dict[str, tuple[str, Path]] = {}
    # 1b) 同名索引：文件基名(小写) -> (guid, 资产文件)
    #     有些 mod 把原版材质放到与 Toolkit 不同的子目录（如 Materials/ 而非 Material/），
    #     相对路径对不上就不会被当作副本，prefab 引用随之悬空（即本次 Engine Olders 1v
    #     火焰材质 6880fbc9/5f4709db 悬空的根因）。同名即视为同一份，下面的等价性判断
    #     会兜底：等价才重定向+删副本，内容不同则保留 mod 版并改名，不会误伤。
    tk_by_name: dict[str, tuple[str, Path]] = {}
    for meta in toolkit_assets.rglob("*.meta"):
        asset = meta.with_suffix("")
        if not asset.is_file():
            continue
        guid = _meta_guid(meta)
        if not guid:
            continue
        try:
            rel = asset.relative_to(toolkit_assets).as_posix().lower()
        except ValueError:
            continue
        tk_by_rel[rel] = (guid, asset)
        tk_by_name.setdefault(asset.stem.lower(), (guid, asset))

    # 2) 找出包内的同名副本，决定重定向还是改名保留
    redirect: dict[str, str] = {}
    drop: set[Path] = set()
    rename: list[tuple[Path, Path]] = []
    for meta in package_assets.rglob("*.meta"):
        asset = meta.with_suffix("")
        if not asset.is_file():
            continue
        pkg_guid = _meta_guid(meta)
        if not pkg_guid:
            continue
        try:
            rel = asset.relative_to(package_assets).as_posix().lower()
        except ValueError:
            continue
        hit = tk_by_rel.get(rel) or tk_by_name.get(asset.stem.lower())
        if hit is None:
            continue
        result["dupes"] += 1
        tk_guid, tk_asset = hit
        if tk_guid == pkg_guid or _assets_equivalent(asset, tk_asset):
            # 同一个东西的副本：引用改指 Toolkit，包内这份删掉
            redirect[pkg_guid] = tk_guid
            drop.add(asset)
            result["redirected"] += 1
        else:
            # 内容确有差异：保留 mod 的，改名避开 Toolkit 同名文件（GUID 不变，引用照旧）
            new_asset = asset.with_name(f"{rename_tag}_{asset.name}")
            rename.append((asset, new_asset))
            result["kept_diff"].append(asset.relative_to(package_assets).as_posix())

    if rename:
        for old, new in rename:
            try:
                new.parent.mkdir(parents=True, exist_ok=True)
                old.rename(new)
                old_meta, new_meta = Path(str(old) + ".meta"), Path(str(new) + ".meta")
                if old_meta.is_file():
                    old_meta.rename(new_meta)
                # 文件改名了，内部的 m_Name 也要跟着改，否则 Odin 刷名字不匹配警告
                if new.suffix.lower() in (".mat", ".asset", ".prefab"):
                    sync_asset_name(new)
            except OSError:
                continue

    if not redirect:
        if result["dupes"]:
            log("[对齐] 与 Toolkit 同名资源 {} 个 全部保留了 mod 版本".format(result["dupes"]))
        return result

    # 3) 把包内所有文本资产里对"待删副本"的引用改写成 Toolkit 的 GUID
    def repl(m: re.Match) -> str:
        new = redirect.get(m.group(1).lower())
        if not new:
            return m.group(0)
        result["refs"] += 1
        return "guid: " + new

    for f in package_assets.rglob("*"):
        if not f.is_file() or f.suffix.lower() not in REWRITE_SUFFIXES:
            continue
        if f in drop:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "guid:" not in text:
            continue
        new_text = GUID_FIELD_RE.sub(repl, text)
        if new_text != text:
            try:
                f.write_text(new_text, encoding="utf-8")
            except OSError:
                continue

    # 4) 删掉包内的重复副本（含 .meta），由 Toolkit 那份顶上
    for asset in drop:
        for p in (asset, Path(str(asset) + ".meta")):
            try:
                if p.is_file():
                    p.unlink()
                    result["removed"] += 1
            except OSError:
                pass

    log("[对齐] 与 Toolkit 同名的原版资源 {} 个 已改指 Toolkit 那份(重写引用 {} 处 移除副本 {} 个)".format(
        result["redirected"], result["refs"], result["removed"]))
    if result["kept_diff"]:
        log("[对齐] [!] {} 个同名资源内容与 Toolkit 不同 已保留 mod 版本并改名 {}".format(
            len(result["kept_diff"]), result["kept_diff"][:8]))
    return result


def repair_toolkit_dangling_refs(
    toolkit_root: Path,
    package_assets: Path | str | None = None,
    log=None,
    backup: bool = True,
) -> dict[str, object]:
    """扫描并自愈 Toolkit 里**已经存在**的悬空引用（部件指向不存在的 GUID）。

    适用场景：用早期/其它流程并已导入的 Toolkit，里面某些部件（最常见是火焰/
    贴图/音效类材质）仍引用着 mod 自己的 GUID，而这些 GUID 在 Toolkit 里不存在
    —— 表现就是 Odin 一片 Missing(Material) / 渲染脚本取不到材质直接 NRE。

    自愈策略（需提供原始 mod 工程目录 `package_assets`，即 AssetRipper 导出的那份）：
    1. 以 Toolkit 现有全部 .meta 的 GUID 为"已知集"，扫出 Toolkit 文本资产里所有
       指向未知 GUID 的引用（即悬空引用）；
    2. 对每个悬空 GUID，去 `package_assets` 里找同名/同 GUID 的原版资产：
       - 原版与 Toolkit 同名资产**等价** → 把 Toolkit 里的引用改指 Toolkit 那份
         （去重，不重复拷入）；
       - 原版与 Toolkit 同名资产**不同**（mod 真改过）→ 把原版**补入** Toolkit
         （保留原 GUID，引用自然就通了）；
       - Toolkit 里**没有**同名资产 → 同样把原版补入 Toolkit（保留原 GUID）。
    3. 实在找不到原版（真孤儿 GUID）→ 写进清单交人工处理。

    不提供 `package_assets` 时只做**扫描 + 清单**，绝不瞎改（避免把好的引用改坏）。
    默认先备份到 `<Toolkit>/_PackToolBackup/<时间>_dangling/`。
    """
    import time
    import shutil

    if log is None:
        log = print
    toolkit_root = Path(toolkit_root)
    tk_assets = toolkit_root / "Assets"
    if not tk_assets.is_dir():
        return {"error": "Toolkit 缺少 Assets 目录", "dangling": 0, "redirected": 0,
                "imported": 0, "unresolved": 0, "manifest": ""}

    # 1) Toolkit 侧索引：guid -> 资产、文件名(小写) -> guid
    tk_known: set[str] = set()
    tk_guid_to_asset: dict[str, Path] = {}
    tk_name_to_guid: dict[str, str] = {}
    for meta in tk_assets.rglob("*.meta"):
        g = _meta_guid(meta)
        if not g:
            continue
        tk_known.add(g)
        asset = meta.with_suffix("")
        tk_guid_to_asset[g] = asset
        if asset.is_file():
            tk_name_to_guid.setdefault(asset.stem.lower(), g)

    # 包侧索引（可选；需提供原始 mod 工程目录才能真正自愈）
    pkg_present = False
    pkg_guid_to_asset: dict[str, Path] = {}
    pkg_name_to_guid: dict[str, str] = {}
    if package_assets:
        pkg = Path(package_assets)
        if pkg.is_dir() and (pkg / "Assets").is_dir():
            pkg = pkg / "Assets"
        if pkg.is_dir():
            pkg_present = True
            for meta in pkg.rglob("*.meta"):
                g = _meta_guid(meta)
                if not g:
                    continue
                asset = meta.with_suffix("")
                pkg_guid_to_asset[g] = asset
                if asset.is_file():
                    pkg_name_to_guid.setdefault(asset.stem.lower(), g)

    # 2) 扫出 Toolkit 里所有指向"非 Toolkit GUID"的悬空引用
    dangling: list[tuple[Path, str]] = []
    for f in tk_assets.rglob("*"):
        if not f.is_file() or f.suffix.lower() not in REWRITE_SUFFIXES:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "guid:" not in text:
            continue
        for g in GUID_FIELD_RE.findall(text):
            gl = g.lower()
            if gl in UNITY_BUILTIN_NULL_GUIDS:
                continue  # Unity 内置占位引用，正常，不算悬空
            if gl not in tk_known:
                dangling.append((f, gl))

    total = len(dangling)
    if total == 0:
        log("[悬空] 未发现悬空引用 Toolkit 已是干净的")
        return {"dangling": 0, "redirected": 0, "imported": 0, "unresolved": 0, "manifest": ""}

    # 3) 对去重后的每个悬空 GUID 制定重定向/补入方案
    redirect: dict[str, str] = {}
    import_plan: list[Path] = []
    imported_names: list[str] = []
    unresolved: list[tuple[str, str]] = []
    seen: set[str] = set()
    for f, g in dangling:
        if g in seen:
            continue
        seen.add(g)
        if not pkg_present or g not in pkg_guid_to_asset:
            unresolved.append((str(f.relative_to(toolkit_root)), g))
            continue
        pkg_asset = pkg_guid_to_asset[g]
        name = pkg_asset.stem.lower()
        tk_g = tk_name_to_guid.get(name)
        if tk_g and tk_g != g:
            tk_asset = tk_guid_to_asset.get(tk_g)
            if tk_asset and _assets_equivalent(pkg_asset, tk_asset):
                # 同名等价：直接指向 Toolkit 那份，不重复拷入
                redirect[g] = tk_g
            else:
                # 同名但内容不同（mod 真改过）：补入原版，保留原 GUID
                import_plan.append(pkg_asset)
        else:
            # Toolkit 没有同名资产：补入原版，保留原 GUID
            import_plan.append(pkg_asset)

    # 4) 把 Toolkit 里对"待重定向 GUID"的引用改写为 Toolkit 的 GUID
    redirected = 0
    if redirect:
        redir_lower = {k.lower(): v for k, v in redirect.items()}
        counter = [0]
        def repl(m: "re.Match") -> str:
            new = redir_lower.get(m.group(1).lower())
            if new:
                counter[0] += 1
                return "guid: " + new
            return m.group(0)
        for f in tk_assets.rglob("*"):
            if not f.is_file() or f.suffix.lower() not in REWRITE_SUFFIXES:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if "guid:" not in text:
                continue
            new_text = GUID_FIELD_RE.sub(repl, text)
            if new_text != text:
                try:
                    f.write_text(new_text, encoding="utf-8")
                except OSError:
                    pass
        redirected = counter[0]

    # 5) 补入 Toolkit 缺失的原版资产（连同 .meta 一起，保留原 GUID）
    imported = 0
    if import_plan and pkg_present:
        for pkg_asset in import_plan:
            try:
                rel = pkg_asset.relative_to(pkg)
            except ValueError:
                continue
            dest = tk_assets / rel
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                copied = False
                if not dest.exists():
                    shutil.copy2(pkg_asset, dest)
                    imported_names.append(pkg_asset.name)
                    imported += 1
                    copied = True
                pkg_meta = Path(str(pkg_asset) + ".meta")
                if pkg_meta.is_file():
                    dest_meta = Path(str(dest) + ".meta")
                    if not dest_meta.exists():
                        shutil.copy2(pkg_meta, dest_meta)
                        copied = True
                if not copied:
                    # 目标已存在（通常同 GUID 同名），跳过即可
                    pass
            except OSError:
                continue

    # 6) 孤儿 GUID 写清单
    manifest = ""
    if unresolved:
        backup_dir = toolkit_root / "_PackToolBackup" / (time.strftime("%Y%m%d_%H%M%S") + "_dangling")
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            manifest = str(backup_dir / "dangling_manifest.txt")
            with open(manifest, "w", encoding="utf-8") as fh:
                fh.write("# 悬空引用清单（共 {} 处，无法自动修复）\n".format(len(unresolved)))
                fh.write("# 格式：文件 | 悬空 GUID\n")
                for fp, g in unresolved:
                    fh.write("{} | {}\n".format(fp, g))
        except OSError:
            manifest = ""

    log("[悬空] 扫描到 {} 处悬空引用".format(total))
    if redirected:
        log("[悬空] 已按同名重定向 {} 处".format(redirected))
    if imported:
        log("[悬空] 已补入 Toolkit 缺失资产 {} 个：{}".format(imported, imported_names[:8]))
    if unresolved:
        log("[悬空] 无法自动修复 {} 处 清单见 {}".format(len(unresolved), manifest))
    if not pkg_present:
        log("[悬空] 未提供原始 mod 工程目录 仅完成扫描+清单 如需自动修复请填写原始 mod 工程目录")

    return {
        "dangling": total,
        "redirected": redirected,
        "imported": imported,
        "unresolved": len(unresolved),
        "manifest": manifest,
    }


def _script_dangling(path: Path, known_guids: set[str]) -> int:
    """数一个 prefab/asset 里有多少处 m_Script 指向 known_guids 里没有的 GUID。"""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    n = 0
    for mm in SCRIPT_REF_RE.finditer(text):
        if mm.group(2).lower() not in known_guids:
            n += 1
    return n


def build_merge_package(
    project_dir: Path,
    pack_path: Path,
    toolkit_root: Path,
    package_dir: Path,
    log=None,
) -> dict[str, object]:
    """裁剪出只含“Toolkit 没有的新内容”的合并包。

    产物不含 .cs/.dll（脚本由 Toolkit 提供，避免 CS0263），prefab 的 m_Script
    已指向 Toolkit 真脚本；新增部件归一化到 Assets/Resources/Parts/<模组名>/，
    自动替换 AssetRipper 空壳着色器（黑板根因），并做 GUID 冲突预检。
    """
    if log is None:
        log = print
    report: dict[str, object] = {"ok": False}
    project_dir = Path(project_dir)
    project_assets = project_dir / "Assets"
    if not project_assets.is_dir():
        report["error"] = "导出工程缺少 Assets 目录"
        return report

    toolkit_map = build_toolkit_guid_map(toolkit_root)
    if not toolkit_map:
        report["error"] = f"未在 Toolkit 中找到脚本 .meta {toolkit_root}"
        return report

    # 1) Toolkit 已有部件（按 prefab 文件名判定，记住路径以便比较谁更"健康"）
    parts_dir = Path(toolkit_root) / "Assets" / "Resources" / "Parts"
    existing_parts: dict[str, Path] = {}
    if parts_dir.is_dir():
        for p in parts_dir.rglob("*.prefab"):
            existing_parts.setdefault(p.stem, p)
    log(f"[合并] Toolkit 已有部件 {len(existing_parts)} 个")

    # 2) stub->toolkit GUID 映射并重写所有 prefab（幂等）
    try:
        mono_classes = collect_monoscript_classes(pack_path)
    except Exception:
        # .pack 解析失败时退化：映射 Toolkit 里全部脚本类
        mono_classes = set(toolkit_map)
    imported_toolkit_guid = {name: g for name, g in toolkit_map.items() if name in mono_classes}
    stub_to_toolkit: dict[str, str] = {}
    stub_guid_to_class: dict[str, str] = {}
    for meta in project_assets.rglob("*.cs.meta"):
        m = re.search(r"^guid:\s*([0-9a-fA-F]+)", meta.read_text(encoding="utf-8", errors="ignore"), re.MULTILINE)
        if not m:
            continue
        cs = meta.with_suffix("").with_suffix(".cs")
        clazz = class_name_of_file(cs)
        g = m.group(1).lower()
        stub_guid_to_class[g] = clazz
        if clazz in imported_toolkit_guid:
            stub_to_toolkit[g] = imported_toolkit_guid[clazz]
    prefabs = sorted(project_assets.rglob("*.prefab"))
    total_rewrite = 0
    rewritten_text: dict[Path, str] = {}
    for prefab in prefabs:
        text, n = rewrite_script_guids(prefab.read_text(encoding="utf-8", errors="ignore"), stub_to_toolkit)
        rewritten_text[prefab] = text
        if n:
            prefab.write_text(text, encoding="utf-8")
            total_rewrite += n
    log(f"[合并] 已重写 {total_rewrite} 处脚本引用")

    # 2.5) 自动处理“黑板”：AssetRipper 反编译不了 SFS 自定义着色器，会留下带
    #      DummyShaderTextExporter 的占位 shader，零件因此渲成纯黑板且**不报错**。
    #      先用 copy 模式就地换真源码（保留 GUID，导出工程自身即可正确渲染），
    #      放在依赖收集之前，这样拷进包里的就是修好的着色器。
    try:
        fix_stub_shaders(project_assets, toolkit_root, log=log, mode="copy")
    except Exception as e:  # 着色器修复失败不应阻断合并
        log(f"[合并] [!] 空壳着色器处理失败 {e}")

    # 3) 挑出新增部件并按文件名去重：归一化到 Resources/Parts 时同名会互相覆盖
    #    「已存在」不等于「不用管」：上一次导入留下的坏部件（脚本全挂）也在里面，
    #    这时 Toolkit 那份的挂空引用数明显更高，必须纳入更新，否则重跑一遍根本修不回来。
    toolkit_known: set[str] = set()
    for meta in Path(toolkit_root).joinpath("Assets").rglob("*.meta"):
        try:
            m = re.search(r"^guid:\s*([0-9a-fA-F]{32})",
                          meta.read_text(encoding="utf-8", errors="ignore"), re.MULTILINE)
        except OSError:
            continue
        if m:
            toolkit_known.add(m.group(1).lower())
    export_known = toolkit_known | set(index_asset_guids(project_assets))
    for meta in project_assets.rglob("*.meta"):
        try:
            m = re.search(r"^guid:\s*([0-9a-fA-F]{32})",
                          meta.read_text(encoding="utf-8", errors="ignore"), re.MULTILINE)
        except OSError:
            continue
        if m:
            export_known.add(m.group(1).lower())

    new_prefabs: list[Path] = []
    updated_prefabs: list[Path] = []
    skipped: list[Path] = []
    duplicate_parts: list[str] = []
    seen_stems: set[str] = set()
    for p in prefabs:
        if p.stem in existing_parts:
            old = existing_parts[p.stem]
            if _script_dangling(old, toolkit_known) > _script_dangling(p, export_known):
                updated_prefabs.append(p)
            else:
                skipped.append(p)
            continue
        if p.stem in seen_stems:
            duplicate_parts.append(str(p.relative_to(project_assets)))
            continue
        seen_stems.add(p.stem)
        new_prefabs.append(p)
    if updated_prefabs:
        log(f"[合并] 其中 {len(updated_prefabs)} 个 Toolkit 里已有但脚本挂空 本次一并更新")
    new_prefabs = new_prefabs + updated_prefabs
    log(f"[合并] 新增部件 {len(new_prefabs)} Toolkit 已有而跳过 {len(skipped)}")
    if duplicate_parts:
        log(f"[合并] [!] {len(duplicate_parts)} 个新增部件文件名重复 只保留第一个 {duplicate_parts[:8]}")

    # 4) 广度收集依赖并拷贝：依赖保留原路径，新增部件归一化到 Resources/Parts
    guid_map = index_asset_guids(project_assets)
    needed = collect_referenced_assets(project_assets, new_prefabs, guid_map)
    package_assets = package_dir / "Assets"
    package_assets.mkdir(parents=True, exist_ok=True)

    new_prefab_set = {p.resolve() for p in new_prefabs}
    deps = [p for p in needed if p.resolve() not in new_prefab_set]
    copied = 0
    for src in deps:
        try:
            rel = src.relative_to(project_assets)
        except ValueError:
            continue
        copied += copy_with_meta(src, package_assets / rel)
    # 新建一层以 .pack 命名的子目录，避免玩家部件和 Toolkit 自带部件混在一起
    sub_name = _parts_subfolder_name(pack_path)
    parts_out = package_assets / "Resources" / "Parts" / sub_name
    parts_out.mkdir(parents=True, exist_ok=True)
    new_names = []
    for prefab in new_prefabs:
        dest = parts_out / prefab.name
        copied += copy_with_meta(prefab, dest)
        new_names.append(prefab.stem)

    # 4.5) 显式补拷 mod 自有脚本 artifacts：情形1=DLL(Plugins)，情形2=ModCode 源码。
    #      依赖收集阶段被 MERGE_SKIP_SUFFIXES 跳过了这两类，必须在此补上，否则贴进
    #      Toolkit 后自定义脚本引用悬空(就是之前『没挂上』的根因之一)。
    mod_custom = _merge_copy_custom_scripts(project_assets, new_prefabs, package_assets, log)
    for p in mod_custom["assets"]:
        needed.add(Path(p))  # 纳入后面的 GUID 冲突预检
    if mod_custom["dll"]:
        log(f"[合并] 已带上 mod 程序集 {mod_custom['dll']} 个(DLL) 自定义脚本引用据此解析")
    if mod_custom["cs"]:
        log(f"[合并] 已带上 ModCode 自定义脚本 {mod_custom['cs']} 个 自定义脚本引用据此解析")

    # 4.6) 合并包里改成 remap：Toolkit 本身就有真着色器，材质重指向它的 GUID
    #      并删掉重复文件，避免 Toolkit 的 Shader 下拉里出现两个同名 SFS/Weird。
    shader_fix: dict[str, object] = {"stubs": 0, "fixed": 0, "refs": 0, "deleted": 0, "unmatched": [], "map": {}}
    try:
        shader_fix = fix_stub_shaders(package_assets, toolkit_root, log=log, mode="remap")
    except Exception as e:  # 着色器修复失败不应阻断合并
        log(f"[合并] [!] 合并包着色器重指向失败 {e}")

    # 4.7) 关键一步：AssetRipper 导出的是「平行 GUID 世界」，mod 复用的原版贴图/
    #      材质/音效/配置在 Toolkit 里本来就有，但 GUID 是 Toolkit 自己那一套。
    #      不按相对路径把包内引用对齐到 Toolkit，零件贴进去后这些引用必定悬空
    #      —— Odin 一片 missing，RenderSortingModule 这类脚本还会因此直接 NRE。
    dup_fix: dict[str, object] = {"dupes": 0, "redirected": 0, "refs": 0, "removed": 0, "kept_diff": [], "empty": True}
    try:
        dup_fix = remap_toolkit_duplicates(
            package_assets, Path(toolkit_root) / "Assets", log=log, rename_tag=sub_name
        )
    except Exception as e:
        log(f"[合并] [!] 同名资源对齐失败 {e}")

    # 4.8) 重映射会删掉重复副本，重新按包内实际文件数统计，README 里的数字才准
    copied = sum(1 for p in package_assets.rglob("*") if p.is_file())

    # 5) GUID 冲突预检：包内资产 GUID 与 Toolkit 已有资产求交
    toolkit_guid_index = index_asset_guids(Path(toolkit_root) / "Assets")
    collisions: list[str] = []
    for src in needed:
        smeta = Path(str(src) + ".meta")
        if not smeta.is_file():
            continue
        m = re.search(r"^guid:\s*([0-9a-fA-F]{32})", smeta.read_text(encoding="utf-8", errors="ignore"), re.MULTILINE)
        if not m:
            continue
        g = m.group(1).lower()
        tk_asset = toolkit_guid_index.get(g)
        if tk_asset is not None and tk_asset.resolve() != src.resolve():
            collisions.append(f"{src.name} ({g[:8]} ) -> Toolkit 已存在 {tk_asset}")
    if collisions:
        log(f"[合并] [!] GUID 冲突 {len(collisions)} 处 拷入后可能与 Toolkit 既有资产撞 GUID")
        for c in collisions[:10]:
            log(f"[合并]    - {c}")

    # 6) 计算新增部件里仍未解析的类，写进使用说明
    merge_unresolved: list[str] = []
    for prefab in new_prefabs:
        for cls in collect_unresolved(rewritten_text.get(prefab, ""), stub_guid_to_class, stub_to_toolkit):
            if cls not in merge_unresolved:
                merge_unresolved.append(cls)
    readme_lines = [
        "# SFS 新增部件合并包\n",
        f"来源 .pack {pack_path.name}\n",
        f"- 新增部件 {len(new_prefabs)} 个 Toolkit 已有并跳过 {len(skipped)} 个 已拷贝资产 {copied} 个文件(含.meta)\n",
    ]
    if mod_custom["dll"] or mod_custom["cs"]:
        readme_lines.append(
            f"- 本包**含 mod 自定义脚本** {mod_custom['dll']} 个程序集(DLL) + {mod_custom['cs']} 个源码(ModCode)"
            " 已与 prefab 引用一一对应 贴进 Toolkit 后无需重新挂接\n"
        )
    else:
        readme_lines.append(
            "- 本包**不含脚本** 脚本由你的 Modding Toolkit 提供 因此**不会重复 不会触发 CS0263**\n"
        )
    readme_lines += [
        "- 用法 把 `Assets/` 里的内容拷进 Toolkit 工程 `Assets/` 保留全部 `.meta`\n",
        f"- 新增部件统一放在 `Assets/Resources/Parts/{sub_name}/` 子目录(以模组名命名) 与 Toolkit 自带部件分开\n",
        "- 新增部件 prefab 的脚本引用已指向 Toolkit 真实脚本 GUID 导入后即能正常解析 可编辑\n",
        "\n---\n",
    ]
    if shader_fix["stubs"]:
        readme_lines.append(
            "- **已自动修复黑板** 检出 AssetRipper 空壳着色器 {} 个 重写材质引用 {} 处"
            " 删除空壳 {} 个 材质现指向 Toolkit 真着色器\n".format(
                shader_fix["stubs"], shader_fix["refs"], shader_fix["deleted"]
            )
        )
        if shader_fix["unmatched"]:
            readme_lines.append(
                f"- [!] 仍有 {len(shader_fix['unmatched'])} 个着色器在 Toolkit 里找不到同名真身 {sorted(set(shader_fix['unmatched']))}\n"
            )
    if dup_fix["redirected"]:
        readme_lines.append(
            "- **已对齐原版资源** {} 个与 Toolkit 同名的贴图/材质/音效/配置 已改指 Toolkit 那一份"
            "(重写引用 {} 处 移除重复副本 {} 个) 这是零件引用不再悬空的关键\n".format(
                dup_fix["redirected"], dup_fix["refs"], dup_fix["removed"]
            )
        )
    if dup_fix["kept_diff"]:
        readme_lines.append(
            "- [!] {} 个同名资源内容与 Toolkit 不同 已保留 mod 版本并加 `{}_` 前缀改名 {}".format(
                len(dup_fix["kept_diff"]), sub_name, dup_fix["kept_diff"][:8]
            ) + "\n"
        )
    if collisions:
        readme_lines.append(f"- **GUID 冲突 {len(collisions)} 处** 请人工核对后再拷入\n")
    if duplicate_parts:
        readme_lines.append(f"- **{len(duplicate_parts)} 个部件文件名重复** 只保留了第一个 {duplicate_parts[:8]}\n")
    if merge_unresolved:
        readme_lines.append(f"- 新增部件中存在 Toolkit 无源码的类 仍可能 Missing(来自 mod 的 CodeAssembly) {merge_unresolved}\n")
    else:
        readme_lines.append("- 未发现新增部件里有 Toolkit 无法解析的脚本类\n")
    (package_dir / "MERGE_README.md").write_text("".join(readme_lines), encoding="utf-8")

    report.update(
        {
            "ok": True,
            "new_parts": len(new_prefabs),
            "updated_parts": len(updated_prefabs),
            "skipped_parts": len(skipped),
            "rewritten_refs": total_rewrite,
            "copied_files": copied,
            "package_dir": str(package_dir),
            "new_part_names": new_names,
            "duplicate_parts": duplicate_parts,
            "guid_collisions": collisions,
            "mod_custom_dll": mod_custom["dll"],
            "mod_custom_cs": mod_custom["cs"],
            "shader_stubs": shader_fix["stubs"],
            "shader_refs": shader_fix["refs"],
            "shader_deleted": shader_fix["deleted"],
            "parts_subfolder": sub_name,
            "dup_redirected": dup_fix["redirected"],
            "dup_refs": dup_fix["refs"],
            "dup_removed": dup_fix["removed"],
            "dup_kept_diff": dup_fix["kept_diff"],
        }
    )
    return report


if __name__ == "__main__":
    _project = sys.argv[1]
    _pack = sys.argv[2]
    _toolkit = sys.argv[3]
    r = align_scripts_to_toolkit(Path(_project), Path(_pack), Path(_toolkit))
    import pprint
    pprint.pprint(r)