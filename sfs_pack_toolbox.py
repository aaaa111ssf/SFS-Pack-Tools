#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SFS Pack Tool 缺失功能补全模块。

本模块只依赖标准库 + 可选 UnityPy，不引入任何新第三方依赖，便于 PyInstaller 打包。
所有函数都是「纯文件系统 + 返回结构化 dict」，不弹窗、不读全局状态，方便单测。

覆盖功能：
  1. list_backups / restore_backup      —— 一键回滚（_PackToolBackup）
  2. preview_merge                      —— 合并前预览 / 差异报告
  3. probe_toolkit_version              —— Toolkit 版本与指纹探测
  4. resolve_asset_ripper_version       —— AssetRipper 版本识别与校验
  5. DiagnosticLog                      —— 日志落盘 + 可分享诊断报告
  6. incremental_plan                   —— 增量重导出
  7. BatchPlan                          —— 批量导出队列
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# 通用
# ---------------------------------------------------------------------------

BACKUP_ROOTNAME = "_PackToolBackup"
# 备份目录名形如 20261019_230222、20261019_230222_dangling、20261019_230222_stubshaders
BACKUP_DIR_RE = re.compile(r"^(\d{8}_\d{6})(?:_([A-Za-z0-9_]+))?$")

# 版本探测时忽略的文件（无关紧要、且不同机器不一样）
_FINGERPRINT_IGNORE_SUFFIXES = {".meta", ".png", ".jpg", ".tga", ".psd", ".wav", ".ogg", ".mp3"}


def _sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def _read_text(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


# ---------------------------------------------------------------------------
# 1. 一键回滚
# ---------------------------------------------------------------------------


@dataclass
class BackupEntry:
    """一条备份记录。"""

    path: Path
    timestamp: str          # 20261019_230222
    kind: str               # "" / "dangling" / "stubshaders" / ...
    files: list[str] = field(default_factory=list)   # 相对备份目录的文件
    manifest: str = ""      # dangling_manifest.txt 之类的人读清单
    source_root: str = ""   # 备份来源相对路径（可能为空）

    @property
    def display(self) -> str:
        k = f" · {self.kind}" if self.kind else ""
        return f"{self.timestamp}{k}（{len(self.files)} 个文件）"

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "kind": self.kind,
            "files": len(self.files),
            "manifest": self.manifest,
            "path": str(self.path),
        }


def list_backups(toolkit_root) -> list[BackupEntry]:
    """列出 Toolkit 下所有备份（新的在前）。

    只认 `_PackToolBackup/<timestamp>[_kind]/` 这一层，避免把用户自己的目录当备份。
    """
    root = Path(toolkit_root) / BACKUP_ROOTNAME
    if not root.is_dir():
        return []
    out: list[BackupEntry] = []
    for child in sorted(root.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        m = BACKUP_DIR_RE.match(child.name)
        if not m:
            continue
        stamp, kind = m.group(1), (m.group(2) or "")
        files: list[str] = []
        manifest = ""
        # 备份目录里可能套了一层 Assets/...，也可能是平铺。统一按递归相对路径记录。
        for f in sorted(child.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(child).as_posix()
            files.append(rel)
            if f.name in ("dangling_manifest.txt", "MERGE_README.md", "RESTORE_README.md"):
                manifest = rel
        out.append(BackupEntry(child, stamp, kind, files, manifest))
    return out


def _backup_target_root(toolkit_root: Path, entry: BackupEntry, rel: str) -> Path | None:
    """把「备份目录里的相对路径」映射回 Toolkit 里的真实位置。

    备份内容有两种形态：
      A) 保留了 Assets/... 前缀（安装器 shutil.copy2(dest, saved) 时 saved 带相对路径）
      B) 平铺的文件名
    这里优先按 A 映射；A 不存在时按文件名在 Toolkit 里找唯一同名文件。
    返回 Toolkit 内的绝对路径，找不到返回 None。
    """
    tk = Path(toolkit_root)
    candidate = tk / rel
    if candidate.parent.is_dir() or candidate.exists():
        return candidate
    name = Path(rel).name
    hits = [p for p in tk.rglob(name) if p.is_file() and BACKUP_ROOTNAME not in p.parts]
    if len(hits) == 1:
        return hits[0]
    return None


def restore_backup(
    toolkit_root,
    entry: BackupEntry | str,
    *,
    dry_run: bool = True,
    only: list[str] | None = None,
    safety_backup: bool = True,
    log=None,
) -> dict:
    """把一条备份还原回 Toolkit。

    默认 **dry_run=True**：只报告「会改哪些文件」，一个字节都不写。
    真正回滚必须显式 `dry_run=False`，且会先把**当前**文件再备份一份
    （`<timestamp>_prerestore`），保证回滚本身也可回滚。

    参数
      only          只还原这些相对路径（None = 全部）
      safety_backup 回滚前是否先备份现状（默认开）
      log           形如 printf 的日志函数

    返回 {ok, entry, restored, missing, skipped, pre_backup, dry_run, details}
    """
    if log is None:
        log = lambda *a, **k: None
    tk = Path(toolkit_root)
    if isinstance(entry, str):
        found = [e for e in list_backups(tk) if e.timestamp == entry or e.path.name == entry]
        if not found:
            return {"ok": False, "error": f"未找到备份 {entry}", "restored": 0,
                    "missing": 0, "skipped": 0, "pre_backup": "", "dry_run": dry_run,
                    "details": []}
        entry = found[0]

    wanted = entry.files
    if only:
        keep = set(only)
        wanted = [f for f in wanted if f in keep]
    # 清单类文件只给人看，不还原
    wanted = [f for f in wanted if not f.endswith(("dangling_manifest.txt", "MERGE_README.md"))]

    plan: list[dict] = []
    for rel in wanted:
        dest = _backup_target_root(tk, entry, rel)
        if dest is None:
            plan.append({"rel": rel, "action": "skip", "reason": "无法映射回 Toolkit 位置"})
            continue
        plan.append({
            "rel": rel,
            "action": "restore",
            "dest": str(dest),
            "src": str(entry.path / rel),
        })
    restorable = [p for p in plan if p["action"] == "restore"]

    result = {
        "ok": True,
        "entry": entry.display,
        "dry_run": dry_run,
        "restored": 0,
        "missing": sum(1 for p in plan if p["action"] == "skip"),
        "skipped": 0,
        "pre_backup": "",
        "details": plan,
    }
    if dry_run:
        result["would_restore"] = len(restorable)
        log(f"[回滚] 预演 {entry.display} 将还原 {len(restorable)} 个文件"
            f"（跳过 {result['missing']}）")
        return result

    pre_backup = ""
    if safety_backup and restorable:
        stamp = time.strftime("%Y%m%d_%H%M%S") + "_prerestore"
        pre_root = tk / BACKUP_ROOTNAME / stamp
        for item in restorable:
            dest = Path(item["dest"])
            if not dest.is_file():
                continue
            try:
                saved = pre_root / dest.relative_to(tk)
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, saved)
            except OSError:
                pass
        pre_backup = str(pre_root)
        result["pre_backup"] = pre_backup

    for item in restorable:
        src, dest = Path(item["src"]), Path(item["dest"])
        if not src.is_file():
            result["missing"] += 1
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            result["restored"] += 1
        except OSError as exc:
            result["skipped"] += 1
            log(f"[回滚] [!] {dest} 还原失败 {exc}")

    log(f"[回滚] 已还原 {result['restored']} 个文件"
        + (f"，回滚前现状备份于 {pre_backup}" if pre_backup else ""))
    return result


# ---------------------------------------------------------------------------
# 2. 合并前预览 / 差异报告
# ---------------------------------------------------------------------------


def _norm_rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def preview_merge(package_dir, toolkit_root) -> dict:
    """比较「合并包」与「Toolkit 现状」，产出导入前可读的差异报告。

    纯只读：不写任何文件。返回
      {ok, adds:[{rel,kind}], skips:[{rel,reason}], replaces:[{rel,reason}],
       conflicts:[...], summary:{add,skip,replace,conflict},
       parts_added:[名字], parts_existing:[名字], assets_new, assets_dup}
    """
    pkg = Path(package_dir) / "Assets"
    tk = Path(toolkit_root) / "Assets"
    if not pkg.is_dir():
        return {"ok": False, "error": f"合并包缺少 Assets 目录 {pkg}", "summary": {}}
    if not tk.is_dir():
        return {"ok": False, "error": f"Toolkit 缺少 Assets 目录 {tk}", "summary": {}}

    tk_files = {_norm_rel(p, tk): p for p in tk.rglob("*") if p.is_file()}
    adds, skips, replaces = [], [], []
    parts_added, parts_existing = [], []

    for src in sorted(pkg.rglob("*")):
        if not src.is_file():
            continue
        rel = _norm_rel(src, pkg)
        out = tk_files.get(rel)
        if out is None:
            adds.append({"rel": rel, "kind": src.suffix.lower().lstrip(".")})
        else:
            # 同名文件：GUID 相同=同一资产的新版本；不同=可能顶掉既有资产
            s_guid = _meta_guid(src)
            d_guid = _meta_guid(out)
            if s_guid and d_guid and s_guid == d_guid:
                replaces.append({"rel": rel, "reason": "同名同 GUID（同资产的新版本）"})
            elif s_guid and d_guid and s_guid != d_guid:
                skips.append({"rel": rel, "reason": "同名不同 GUID（Toolkit 已有另一份，默认不覆盖）"})
            else:
                skips.append({"rel": rel, "reason": "同名（无 .meta 无法判定）"})

        if src.suffix.lower() == ".prefab":
            stem = src.stem
            existing = [p for p in tk_files.values() if p.name == src.name]
            if existing:
                parts_existing.append(stem)
            else:
                parts_added.append(stem)

    conflicts = _detect_null_meta(adds, pkg)

    return {
        "ok": True,
        "package": str(package_dir),
        "toolkit": str(toolkit_root),
        "adds": adds,
        "skips": skips,
        "replaces": replaces,
        "conflicts": conflicts,
        "parts_added": sorted(parts_added),
        "parts_existing": sorted(parts_existing),
        "summary": {
            "add": len(adds),
            "skip": len(skips),
            "replace": len(replaces),
            "conflict": len(conflicts),
            "parts_added": len(parts_added),
            "parts_existing": len(parts_existing),
        },
    }


def _meta_guid(p) -> str:
    """读同目录同名 .meta 的 guid；p 本身是 .meta 则直接读它。"""
    p = Path(p)
    meta = p if p.name.endswith(".meta") else Path(str(p) + ".meta")
    if not meta.is_file():
        return ""
    m = re.search(r"^guid:\s*([0-9a-fA-F]{32})", _read_text(meta), re.MULTILINE)
    return m.group(1).lower() if m else ""


def _detect_null_meta(adds: list[dict], pkg_assets: Path) -> list[dict]:
    """新增资产里有 .meta 缺失的 → 导入后 GUID 会由 Unity 现场生成，引用可能错位。"""
    out = []
    for item in adds:
        rel = item["rel"]
        if rel.endswith(".meta"):
            continue
        f = pkg_assets / rel
        if not f.is_file():
            continue
        if not Path(str(f) + ".meta").is_file():
            out.append({"rel": rel, "reason": "缺少 .meta（GUID 将由 Unity 重新生成）"})
    return out


def format_preview(preview: dict, *, max_lines: int = 40) -> list[str]:
    """把 preview_merge 的结果转成给人看的行（中英可再包一层翻译）。"""
    if not preview.get("ok"):
        return [f"[预览] [!] {preview.get('error', '未知错误')}"]
    s = preview.get("summary") or {}
    lines = [
        f"[预览] 新增 {s.get('add', 0)} 个文件 · 替换 {s.get('replace', 0)} · "
        f"跳过 {s.get('skip', 0)} · 需注意 {s.get('conflict', 0)}",
        f"[预览] 新部件 {s.get('parts_added', 0)} 个 · 与 Toolkit 同名部件 {s.get('parts_existing', 0)} 个",
    ]
    if preview.get("parts_added"):
        names = preview["parts_added"][:12]
        lines.append("[预览] 新部件：" + ", ".join(names) + ("..." if len(preview["parts_added"]) > 12 else ""))
    for c in (preview.get("conflicts") or [])[:max_lines]:
        lines.append(f"[预览]   ! {c['rel']} —— {c['reason']}")
    for r in (preview.get("skips") or [])[:max_lines]:
        lines.append(f"[预览]   - 跳过 {r['rel']} —— {r['reason']}")
    return lines


# ---------------------------------------------------------------------------
# 3. Toolkit 版本探测与指纹
# ---------------------------------------------------------------------------

_UNITY_VERSION_RE = re.compile(r"m_EditorVersion:\s*([0-9][^\s\r\n]*)")
_TOOLKIT_VERSION_RES = (
    re.compile(r'ToolkitVersion\s*=\s*"([^"]+)"'),
    re.compile(r'ToolkitVersion\s*=\s*([0-9][\w.\-]*)'),
    re.compile(r'"toolkit[_-]?version"\s*:\s*"([^"]+)"', re.IGNORECASE),
)


def probe_toolkit_version(toolkit_root) -> dict:
    """探测 Toolkit 的 Unity 版本、Toolkit 自身版本号，并算一个稳定指纹。

    指纹 = 对 Assets/Scripts 下所有非资源文件的（相对路径 + 大小 + 内容 sha1）排序后 sha1。
    用途：两次导入之间对比指纹，指纹变了说明 Toolkit 换过版本 —— 这正是「脚本全挂」
    最常见的原因，比让用户自己猜要靠谱。

    返回 {ok, unity_version, toolkit_version, fingerprint, script_files, root, error}
    """
    root = Path(toolkit_root)
    scripts = root / "Assets" / "Scripts"
    if not scripts.is_dir():
        return {"ok": False, "error": f"未找到 Assets/Scripts：{scripts}",
                "unity_version": "", "toolkit_version": "", "fingerprint": "",
                "script_files": 0, "root": str(root)}

    unity_version = ""
    pv = root / "ProjectSettings" / "ProjectVersion.txt"
    if pv.is_file():
        m = _UNITY_VERSION_RE.search(_read_text(pv))
        if m:
            unity_version = m.group(1)

    toolkit_version = ""
    for cs in sorted(scripts.rglob("*.cs")):
        if "version" not in cs.stem.lower():
            continue
        text = _read_text(cs)
        for rx in _TOOLKIT_VERSION_RES:
            m = rx.search(text)
            if m:
                toolkit_version = m.group(1)
                break
        if toolkit_version:
            break
    if not toolkit_version:
        # 退而求其次：读 Assets 下任意 version.json
        for cand in (root / "Assets" / "version.json", root / "version.json"):
            if cand.is_file():
                try:
                    data = json.loads(_read_text(cand))
                except (json.JSONDecodeError, OSError):
                    continue
                if isinstance(data, dict):
                    toolkit_version = str(data.get("version") or data.get("ToolkitVersion") or "")
                if toolkit_version:
                    break

    entries: list[str] = []
    for f in sorted(scripts.rglob("*")):
        if not f.is_file() or f.suffix.lower() in _FINGERPRINT_IGNORE_SUFFIXES:
            continue
        rel = _norm_rel(f, scripts)
        try:
            size = f.stat().st_size
        except OSError:
            continue
        entries.append(f"{rel}\t{size}\t{_file_sha1(f)}")
    fingerprint = _sha1_text("\n".join(entries)) if entries else ""

    return {
        "ok": True,
        "root": str(root),
        "unity_version": unity_version,
        "toolkit_version": toolkit_version,
        "fingerprint": fingerprint,
        "script_files": len(entries),
        "error": "",
    }


def compare_toolkit_fingerprint(stored: str, current: str) -> str:
    """对比历史指纹。返回 'same' / 'changed' / 'unknown'。"""
    if not stored or not current:
        return "unknown"
    return "same" if stored == current else "changed"


# ---------------------------------------------------------------------------
# 4. AssetRipper 版本识别与校验
# ---------------------------------------------------------------------------

# 本工具适配过、且 README 承诺内置的版本；其它版本可用但会提示
RECOMMENDED_ASSET_RIPPER = "1.1.4"


def resolve_asset_ripper_version(executable) -> dict:
    """识别 AssetRipper 可执行文件的版本。

    两条路都试：`--version` 输出、Windows 文件版本信息。都拿不到就返回 unknown，
    **不阻断流程**（老版本 AssetRipper 可能压根没有 --version）。

    返回 {ok, path, version, source, compatible, error}
    """
    exe = Path(executable) if executable else None
    out = {"ok": False, "path": str(exe) if exe else "", "version": "",
           "source": "", "compatible": None, "error": ""}
    if exe is None or not exe.is_file():
        out["error"] = "可执行文件不存在"
        return out

    # 1) --version
    try:
        proc = subprocess.run(
            [str(exe), "--version"],
            capture_output=True, text=True, timeout=20,
            encoding="utf-8", errors="ignore",
        )
        text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        m = re.search(r"(\d+\.\d+(?:\.\d+)?(?:[-.][\w]+)?)", text)
        if m:
            out.update(ok=True, version=m.group(1), source="--version")
    except (OSError, subprocess.SubprocessError):
        pass

    # 2) Windows 文件版本（PE 资源），用 PowerShell 取，避免额外依赖
    if not out["version"]:
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 f"(Get-Item -LiteralPath '{exe}').VersionInfo.FileVersion"],
                capture_output=True, text=True, timeout=20,
                encoding="utf-8", errors="ignore",
            )
            m = re.search(r"(\d+\.\d+(?:\.\d+)?)", proc.stdout or "")
            if m:
                out.update(ok=True, version=m.group(1), source="file-version")
        except (OSError, subprocess.SubprocessError):
            pass

    if out["version"]:
        out["compatible"] = out["version"].startswith(RECOMMENDED_ASSET_RIPPER)
    else:
        out["error"] = "无法识别版本（不影响使用，仅无法做兼容性提示）"
    return out


# ---------------------------------------------------------------------------
# 5. 日志落盘 + 可分享诊断报告
# ---------------------------------------------------------------------------


class DiagnosticLog:
    """把界面日志同时写进文件，并在结束时生成可分享的诊断报告。

    用法：
        dlog = DiagnosticLog(log_dir, app_version="2.3.3")
        dlog.info("开始导出")
        ...
        dlog.close(extra={"pack": "abc.pack"})   # 生成 <timestamp>_report.md
    """

    def __init__(self, log_dir, *, app_version: str = "", keep_days: int = 30):
        self.dir = Path(log_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.stamp = time.strftime("%Y%m%d_%H%M%S")
        self.log_path = self.dir / f"{self.stamp}.log"
        self.app_version = app_version
        self.keep_days = keep_days
        self._lines: list[str] = []
        self._report_extra: dict | None = None
        self._report_path: str = ""
        self._fh = None
        try:
            self._fh = open(self.log_path, "w", encoding="utf-8")
        except OSError:
            self._fh = None
        self._prune()

    def _prune(self) -> None:
        """按保留天数清理旧日志，避免日志目录无限膨胀。"""
        if self.keep_days <= 0:
            return
        cutoff = time.time() - self.keep_days * 86400
        for f in sorted(self.dir.glob("*")):
            if not f.is_file():
                continue
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                continue

    def _write(self, text: str) -> None:
        self._lines.append(text)
        if self._fh:
            try:
                self._fh.write(text + "\n")
                self._fh.flush()
            except (OSError, ValueError):
                pass

    def info(self, text: str) -> None:
        self._write(f"{time.strftime('%H:%M:%S')}  {text}")

    __call__ = info

    def close(self, extra: dict | None = None) -> str:
        """收尾：写诊断报告，返回报告路径（失败返回空串）。

        允许重复调用（`with` 退出时会再调一次）：extra 只在首次调用时生效，
        第二次调用返回已生成的报告路径而不是覆盖成空 extra。
        """
        if extra and self._report_extra is None:
            self._report_extra = dict(extra)
        if self._report_path:
            return self._report_path
        if self._fh:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None
        report = self.dir / f"{self.stamp}_report.md"
        lines = [
            "# SFS Pack Tool 诊断报告",
            "",
            f"- 时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"- 工具版本：{self.app_version or '未知'}",
            f"- Python：{_py_version()}",
        ]
        for k, v in (self._report_extra or {}).items():
            lines.append(f"- {k}：{v}")
        lines += ["", "## 日志", "", "```"]
        lines += self._lines[-400:]
        lines += ["```", ""]
        try:
            report.write_text("\n".join(lines), encoding="utf-8")
            self._report_path = str(report)
            return self._report_path
        except OSError:
            return ""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _py_version() -> str:
    import platform
    return f"{platform.python_version()} ({platform.system()} {platform.machine()})"


# ---------------------------------------------------------------------------
# 6. 增量重导出
# ---------------------------------------------------------------------------


def pack_fingerprint(pack_path) -> str:
    """给 .pack 算指纹（大小 + sha1）。同内容重导可直接复用上次结果。"""
    p = Path(pack_path)
    try:
        size = p.stat().st_size
    except OSError:
        return ""
    return f"{size}:{_file_sha1(p)}"


def load_export_index(index_path) -> dict:
    try:
        data = json.loads(_read_text(index_path))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def incremental_plan(
    pack_path,
    toolkit_root,
    index_path,
    toolkit_fingerprint: str = "",
) -> dict:
    """判断这次导出能否跳过 / 需要全量。

    跳过条件（三者同时满足）：
      1. 同一个 .pack（大小+sha1 完全一致）
      2. 同一个 Toolkit（指纹一致）
      3. 上次导入的部件现在仍在 Toolkit 里

    返回 {action:"skip"|"full", reason, pack_fingerprint, last_export, missing_parts}
    """
    cur_pack = pack_fingerprint(pack_path)
    idx = load_export_index(index_path)
    out = {
        "action": "full",
        "reason": "",
        "pack_fingerprint": cur_pack,
        "last_export": "",
        "missing_parts": [],
    }
    if not cur_pack:
        out["reason"] = "无法读取 .pack"
        return out
    entry = (idx.get("packs") or {}).get(str(Path(pack_path).resolve()).lower()) or {}
    if not entry:
        out["reason"] = "首次导出这个包"
        return out
    if entry.get("fingerprint") != cur_pack:
        out["reason"] = "包内容有变化"
        return out
    if toolkit_fingerprint and entry.get("toolkit_fingerprint") != toolkit_fingerprint:
        out["reason"] = "Toolkit 指纹变了（疑似换过版本）"
        return out

    tk_parts = Path(toolkit_root) / "Assets" / "Resources" / "Parts"
    missing = []
    if not tk_parts.is_dir():
        out["reason"] = "Toolkit 里没有 Resources/Parts"
        return out
    for name in entry.get("parts") or []:
        if not list(tk_parts.rglob(f"{name}.prefab")):
            missing.append(name)
    if missing:
        out.update(reason=f"{len(missing)} 个上次导入的部件已不在 Toolkit 里", missing_parts=missing)
        return out

    out.update(action="skip", last_export=entry.get("at", ""),
               reason="包与 Toolkit 都没变，且部件仍在")
    return out


def record_export(index_path, pack_path, *, parts: list[str], toolkit_fingerprint: str = "",
                  extra: dict | None = None) -> dict:
    """记录一次成功导出，供下次 incremental_plan 判断。"""
    idx = load_export_index(index_path)
    idx.setdefault("version", 1)
    idx.setdefault("packs", {})
    key = str(Path(pack_path).resolve()).lower()
    idx["packs"][key] = {
        "fingerprint": pack_fingerprint(pack_path),
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "parts": sorted(parts or []),
        "toolkit_fingerprint": toolkit_fingerprint,
        **(extra or {}),
    }
    Path(index_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        Path(index_path).write_text(
            json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return idx


# ---------------------------------------------------------------------------
# 7. 批量导出
# ---------------------------------------------------------------------------


@dataclass
class BatchItem:
    pack: Path
    output: Path
    status: str = "pending"     # pending / running / ok / failed / skipped
    message: str = ""


class BatchPlan:
    """批量导出队列：收集多个 .pack，逐个执行，单项失败不影响其它项。

    设计成「可注入执行函数」，方便 GUI 里接真实导出、单测里接假函数。
    """

    def __init__(self, packs, output_root, *, log=None):
        self.items: list[BatchItem] = []
        root = Path(output_root)
        seen: set[str] = set()
        used_out: set[str] = set()          # 已占用的输出目录名（大小写不敏感）
        for p in packs:
            p = Path(p)
            key = str(p.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            # 两个不同目录下的同名 .pack 会算出同一个输出目录，后一个导出前的
            # rmtree 会把前一个的成果删掉。这里按「父目录名」去重，仍冲突再加序号。
            name = p.stem
            if name.lower() in used_out:
                parent = p.parent.name.strip() or "mod"
                name = f"{p.stem}_{parent}"
                n = 2
                while name.lower() in used_out:
                    name = f"{p.stem}_{parent}_{n}"
                    n += 1
            used_out.add(name.lower())
            self.items.append(BatchItem(pack=p, output=root / name))
        self.log = log or (lambda *a, **k: None)

    def __len__(self) -> int:
        return len(self.items)

    def run(self, executor, *, stop_on_error: bool = False) -> dict:
        """executor(item, log) -> bool/None。返回汇总。"""
        ok = failed = skipped = 0
        for item in self.items:
            if item.status in ("ok", "skipped"):
                continue
            item.status = "running"
            try:
                result = executor(item, self.log)
            except Exception as exc:      # 单项异常不能中断整批
                item.status = "failed"
                item.message = f"{type(exc).__name__}: {exc}"
                failed += 1
                self.log(f"[批量] [!] {item.pack.name} 失败 {item.message}")
                if stop_on_error:
                    break
                continue
            if result is False:
                item.status = "failed"
                item.message = item.message or "执行函数返回 False"
                failed += 1
                if stop_on_error:
                    break
            elif result == "skip":
                item.status = "skipped"
                skipped += 1
                self.log(f"[批量] - {item.pack.name} 已跳过")
            else:
                item.status = "ok"
                ok += 1
                self.log(f"[批量] ✓ {item.pack.name} 完成")
        return {
            "total": len(self.items),
            "ok": ok,
            "failed": failed,
            "skipped": skipped,
            "items": [
                {"pack": str(i.pack), "status": i.status, "message": i.message}
                for i in self.items
            ],
        }

    def summary_lines(self) -> list[str]:
        lines = [f"[批量] 共 {len(self.items)} 个包"]
        for i in self.items:
            mark = {"ok": "✓", "failed": "✗", "skipped": "-", "running": "…"}.get(i.status, "?")
            lines.append(f"[批量]   {mark} {i.pack.name}"
                         + (f" —— {i.message}" if i.message else ""))
        return lines
