#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import base64
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
# 单文件 EXE 运行时解压到临时目录；AssetRipper 需放在 EXE 旁而非临时目录。
RUNTIME_DATA_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else SCRIPT_DIR
ASSET_RIPPER_REPOSITORY = "https://github.com/AssetRipper/AssetRipper/releases/latest/download"
ASSET_RIPPER_CRASH_CODES = {3221226505, -1073740791}
BUILD_KEYS = ("WindowsBuild", "AndroidBuild", "MacBuild", "IOS_Build")


class ExportError(RuntimeError):
    """导出过程中的可预期错误（嵌套影响链上的代码缩进）。"""


class AssetRipperExitError(ExportError):
    def __init__(self, returncode: int, log_path: Path):
        self.returncode = returncode
        self.log_path = log_path
        super().__init__(
            f"AssetRipper 启动后立即退出 退出码 {returncode} 日志 {log_path}\n"
            f"日志末尾\n{log_tail(log_path)}"
        )


def log(message: str) -> None:
    print(message, flush=True)


def safe_remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def platform_asset_name() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arm64 = machine in {"arm64", "aarch64"}

    if system == "windows":
        return "AssetRipper_win_arm64.zip" if arm64 else "AssetRipper_win_x64.zip"
    if system == "darwin":
        return "AssetRipper_mac_arm64.tar.xz" if arm64 else "AssetRipper_mac_x64.tar.xz"
    if system == "linux":
        return "AssetRipper_linux_arm64.tar.xz" if arm64 else "AssetRipper_linux_x64.tar.xz"
    raise ExportError(f"暂不支持的操作系统 {platform.system()} 请使用 --asset-ripper 指定 AssetRipper 可执行文件")


def executable_candidates(directory: Path) -> Iterable[Path]:
    names = {"AssetRipper.GUI.Free", "AssetRipper.GUI.Free.exe", "AssetRipper.GUI"}
    for candidate in directory.rglob("*"):
        if candidate.is_file() and candidate.name in names:
            yield candidate


def bundled_asset_ripper_candidates() -> list[Path]:
    """在【打包内置】与【工程 third_party】里查找自带 AssetRipper，避免联网下载卡死。

    优先级：exe/_MEIPASS 内 third_party -> 源码目录 third_party -> 旧约定 .assetripper。
    """
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))          # 单文件 EXE 解压目录（spec datas 里的 third_party）
    if not getattr(sys, "frozen", False):
        roots.append(SCRIPT_DIR)             # 源码模式：build_kit/third_party/...
    roots.append(RUNTIME_DATA_DIR)           # 旧版约定 exe/脚本旁 .assetripper

    result: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        for sub in ("third_party/assetripper-1.1.4", "third_party/assetripper", ".assetripper"):
            directory = root / sub
            if not directory.is_dir():
                continue
            for candidate in executable_candidates(directory):
                key = str(candidate.resolve())
                if key not in seen:
                    seen.add(key)
                    result.append(candidate)
    return result


def _validate_zip_members(archive: zipfile.ZipFile, root: Path) -> None:
    """校验 zip 内所有成员都在 root 之下，拒绝绝对路径 / .. 路径穿越。"""
    root = root.resolve()
    for info in archive.infolist():
        name = info.filename
        if name.startswith("/") or name.startswith("\\") or ":" in name.split("/", 1)[0]:
            raise ExportError(f"压缩包含非法绝对路径成员 {name}")
        dest = (root / name).resolve()
        if dest != root and root not in dest.parents:
            raise ExportError(f"压缩包成员路径越界 路径穿越 {name}")


def install_asset_ripper(tool_directory: Path, version: str | None = None) -> Path:
    """下载官方发行包，解压后返回 GUI Free 可执行文件。"""
    asset_name = platform_asset_name()
    url = (
        f"https://github.com/AssetRipper/AssetRipper/releases/download/{version}/{asset_name}"
        if version else f"{ASSET_RIPPER_REPOSITORY}/{asset_name}"
    )
    download_path = tool_directory.parent / f"{version or 'latest'}_{asset_name}"

    tool_directory.mkdir(parents=True, exist_ok=True)
    label = f"兼容版 {version}" if version else "最新版"
    log(f"[*] 未找到 AssetRipper 正在下载{label} {asset_name}")
    try:
        with urllib.request.urlopen(url, timeout=60) as response, download_path.open("wb") as output:
            shutil.copyfileobj(response, output)
    except urllib.error.URLError as exc:
        raise ExportError(f"下载 AssetRipper 失败 {exc} 可手动下载后使用 --asset-ripper 指定可执行文件") from exc

    try:
        if asset_name.endswith(".zip"):
            root = tool_directory.resolve()
            with zipfile.ZipFile(download_path) as archive:
                _validate_zip_members(archive, root)
                archive.extractall(root)
        else:
            with tarfile.open(download_path, mode="r:xz") as archive:
                # filter="data" 仅 Python>=3.12 支持；旧版本退化为默认提取（AssetRipper 为官方可信包）。
                if sys.version_info >= (3, 12):
                    archive.extractall(tool_directory, filter="data")
                else:
                    archive.extractall(tool_directory)
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise ExportError(f"解压 AssetRipper 失败 {exc}") from exc
    finally:
        if download_path.exists():
            download_path.unlink()

    candidates = list(executable_candidates(tool_directory))
    if not candidates:
        raise ExportError("AssetRipper 已下载 但未找到 AssetRipper.GUI.Free 可执行文件")

    executable = candidates[0]
    if os.name != "nt":
        executable.chmod(executable.stat().st_mode | 0o111)
    return executable


def resolve_asset_ripper(user_value: str | None, auto_download: bool) -> Path:
    if user_value:
        candidate = Path(user_value).expanduser().resolve()
        if not candidate.is_file():
            raise ExportError(f"指定的 AssetRipper 不存在 {candidate}")
        return candidate

    bundled = bundled_asset_ripper_candidates()
    if bundled:
        executable = bundled[0]
        if os.name != "nt":
            executable.chmod(executable.stat().st_mode | 0o111)
        return executable
    if not auto_download:
        hint = Path(getattr(sys, "_MEIPASS", RUNTIME_DATA_DIR)) / "third_party" / "assetripper-1.1.4"
        raise ExportError(
            f"未找到 AssetRipper 内置版本缺失 请确认以下位置存在"
            f"AssetRipper.GUI.Free.exe {hint} 或使用 --asset-ripper 指定其它可执行文件"
        )
    return install_asset_ripper(RUNTIME_DATA_DIR / ".assetripper")


def read_pack(input_path: Path) -> dict:
    try:
        with input_path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExportError(f"无法读取 .pack JSON {exc}") from exc
    if not isinstance(data, dict):
        raise ExportError(".pack 根节点必须是 JSON 对象")
    return data


def decode_pack_resources(input_path: Path, destination: Path) -> list[Path]:
    """将 Base64 AssetBundle 和可选 CodeAssembly 写入临时目录。"""
    data = read_pack(input_path)
    destination.mkdir(parents=True, exist_ok=True)
    bundles: list[Path] = []

    for key in BUILD_KEYS:
        value = data.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            log(f"[!] 跳过 {key} 该字段不是 Base64 字符串")
            continue
        try:
            raw = base64.b64decode(value, validate=True)
        except (ValueError, UnicodeError) as exc:
            log(f"[!] 跳过 {key} Base64 解码失败 {exc}")
            continue
        if not raw.startswith(b"UnityFS"):
            log(f"[!] 跳过 {key} 解码内容不是 UnityFS AssetBundle")
            continue
        bundle_path = destination / f"{key}.bundle"
        bundle_path.write_bytes(raw)
        bundles.append(bundle_path)
        log(f"[+] 已解码 {key} {len(raw):,} 字节")

    code_assembly = data.get("CodeAssembly")
    if isinstance(code_assembly, str) and code_assembly:
        try:
            assembly_bytes = base64.b64decode(code_assembly, validate=True)
            assembly_path = destination / "CodeAssembly.dll"
            assembly_path.write_bytes(assembly_bytes)
            log(f"[+] 已解码 CodeAssembly {len(assembly_bytes):,} 字节")
        except (ValueError, UnicodeError) as exc:
            log(f"[!] CodeAssembly 解码失败 继续只导出资源 {exc}")

    if not bundles:
        keys = ",".join(BUILD_KEYS)
        raise ExportError(f"未在 .pack 中找到可用 UnityFS AssetBundle 检查字段 {keys}")
    return bundles


def unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def log_tail(log_path: Path, limit: int = 4000) -> str:
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace").strip()
        return text[-limit:] if text else "日志为空"
    except OSError as exc:
        return f"无法读取日志 {exc}"


def has_unsupported_advanced_options(log_path: Path) -> bool:
    text = log_tail(log_path).lower()
    return "unrecognized command or argument '--headless'" in text or "'--log' was not matched" in text


def wait_for_server(base_url: str, process: subprocess.Popen[object], log_path: Path, timeout: float = 25.0) -> None:
    deadline = time.monotonic() + timeout
    latest_error = "服务未响应"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssetRipperExitError(process.returncode, log_path)
        try:
            with urllib.request.urlopen(f"{base_url}/", timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            latest_error = str(exc)
        time.sleep(0.4)
    raise ExportError(f"等待 AssetRipper 服务超时 {latest_error} 日志 {log_path}")


def post_path(base_url: str, endpoint: str, target_path: Path) -> None:
    body = urllib.parse.urlencode({"path": str(target_path)}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}{endpoint}",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        # AssetRipper 正常情况下会以 302 跳回首页；urllib 会自动跟随该跳转。
        with urllib.request.urlopen(request, timeout=900) as response:
            response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ExportError(f"AssetRipper 请求 {endpoint} 失败 {exc}") from exc


def start_asset_ripper(
    executable: Path, port: int, log_path: Path, compatibility_mode: bool = False
) -> subprocess.Popen[object]:
    command = (
        [str(executable), "--port", str(port), "--launch-browser", "false"]
        if compatibility_mode
        else [str(executable), "--headless", "--port", str(port), "--log", "--log-path", str(log_path)]
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8")
    try:
        return subprocess.Popen(
            command,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=str(executable.parent),
        )
    except OSError as exc:
        log_file.close()
        raise ExportError(f"无法启动 AssetRipper {exc}") from exc


def stop_process(process: subprocess.Popen[object]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def count_files(root: Path, extensions: set[str]) -> int:
    if not root.is_dir():
        return 0
    return sum(1 for item in root.rglob("*") if item.is_file() and item.suffix.lower() in extensions)


def list_project_files(directory: Path) -> list[str]:
    if not directory.is_dir():
        return []
    return sorted(str(item.relative_to(directory)) for item in directory.rglob("*") if item.is_file())


# SFS 把零件自己的贴图/音频以 byte[] 塞进 "Pack Data" ScriptableObject，导出后就是
# .asset 文件里的一段 base64/hex 载荷——它**不会**自动变成可播放的 .wav/.ogg。
# 这里把它们识别出来，让用户能一眼确认「音频 Pack Data 确实保留下来了」。
AUDIO_SIGNATURES = (
    (b"RIFF", ".wav"),
    (b"OggS", ".ogg"),
    (b"ID3", ".mp3"),
    (b"fLaC", ".flac"),
    (b"\xff\xfb", ".mp3"),
    (b"\xff\xf3", ".mp3"),
    (b"\xff\xf2", ".mp3"),
)
TEXTURE_SIGNATURES = (
    (b"\x89PNG", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"DDS ", ".dds"),
    (b"GIF8", ".gif"),
    (b"BM", ".bmp"),
)
# 超过这个大小的 .asset 不逐字节扫，避免异常文件拖垮导出
PACK_DATA_SCAN_LIMIT = 64 * 1024 * 1024


def _payload_candidates(text: str):
    """从 Unity YAML 里取出可能的二进制载荷：byte[] 会被写成 base64 或 hex 长串。"""
    for m in re.finditer(r"[A-Za-z0-9+/]{64,}={0,2}", text):
        try:
            data = base64.b64decode(m.group(), validate=False)
        except (ValueError, UnicodeError):
            continue
        if len(data) >= 64:
            yield data
    for m in re.finditer(r"[0-9a-fA-F]{128,}", text):
        raw = m.group()
        if len(raw) % 2:
            raw = raw[:-1]
        try:
            data = bytes.fromhex(raw)
        except ValueError:
            continue
        if len(data) >= 64:
            yield data


def classify_payload(data: bytes) -> str:
    """判断一段字节是什么：'audio:wav' / 'texture:png' / '' 表示认不出。"""
    head = data[:64]
    for sig, ext in AUDIO_SIGNATURES:
        if head.startswith(sig):
            return f"audio:{ext}"
    for sig, ext in TEXTURE_SIGNATURES:
        if head.startswith(sig):
            return f"texture:{ext}"
    return ""


def scan_pack_data_payloads(assets_dir: Path) -> dict:
    """扫 .asset（SFS 的 Pack Data 就落在这些文件里）内嵌的音频/贴图字节流。

    返回 {"asset_files","pack_data_files","audio_pack_files","audio_kinds",
          "audio_samples","texture_pack_files","texture_samples"}
    """
    assets = Path(assets_dir)
    result: dict = {
        "asset_files": 0,
        "pack_data_files": 0,
        "audio_pack_files": 0,
        "audio_kinds": {},
        "audio_samples": [],
        "texture_pack_files": 0,
        "texture_samples": [],
    }
    if not assets.is_dir():
        return result
    for f in assets.rglob("*.asset"):
        result["asset_files"] += 1
        try:
            if f.stat().st_size > PACK_DATA_SCAN_LIMIT:
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        kinds: set[str] = set()
        for data in _payload_candidates(text):
            kind = classify_payload(data)
            if kind:
                kinds.add(kind)
        if not kinds:
            continue
        result["pack_data_files"] += 1
        rel = str(f.relative_to(assets))
        audios = sorted(k for k in kinds if k.startswith("audio:"))
        textures = sorted(k for k in kinds if k.startswith("texture:"))
        if audios:
            result["audio_pack_files"] += 1
            for k in audios:
                key = k.split(":", 1)[1]
                result["audio_kinds"][key] = result["audio_kinds"].get(key, 0) + 1
            if len(result["audio_samples"]) < 20:
                result["audio_samples"].append({"file": rel, "kinds": [k.split(":", 1)[1] for k in audios]})
        if textures:
            result["texture_pack_files"] += 1
            if len(result["texture_samples"]) < 20:
                result["texture_samples"].append({"file": rel, "kinds": [k.split(":", 1)[1] for k in textures]})
    return result


def validate_project(project_dir: Path) -> dict:
    assets_dir = project_dir / "Assets"
    if not assets_dir.is_dir():
        raise ExportError("AssetRipper 完成后未生成 Assets 目录")

    texture_extensions = {".png", ".jpg", ".jpeg", ".tga", ".bmp", ".gif", ".psd", ".exr", ".hdr", ".dds"}
    audio_extensions = {".wav", ".mp3", ".ogg", ".aiff", ".flac"}
    material_extensions = {".mat"}
    shader_extensions = {".shader", ".shadergraph"}
    script_extensions = {".cs", ".dll"}
    asset_extensions = {".asset"}
    prefab_extensions = {".prefab"}
    meta_extensions = {".meta"}

    prefabs: list[Path] = []
    yaml_prefabs = 0
    counts = {k: 0 for k in ("texture", "material", "shader", "script", "audio", "asset_file", "meta_file")}
    total_files = 0
    for item in assets_dir.rglob("*"):
        if not item.is_file():
            continue
        total_files += 1
        suffix = item.suffix.lower()
        if suffix in prefab_extensions:
            prefabs.append(item)
            try:
                if item.read_bytes().startswith(b"%YAML 1.1"):
                    yaml_prefabs += 1
            except OSError:
                pass
        if suffix in texture_extensions:
            counts["texture"] += 1
        elif suffix in material_extensions:
            counts["material"] += 1
        elif suffix in shader_extensions:
            counts["shader"] += 1
        elif suffix in script_extensions:
            counts["script"] += 1
        elif suffix in audio_extensions:
            counts["audio"] += 1
        elif suffix in asset_extensions:
            counts["asset_file"] += 1
        elif suffix in meta_extensions:
            counts["meta_file"] += 1

    if not prefabs:
        raise ExportError("AssetRipper 完成后未找到任何 .prefab 文件")
    if yaml_prefabs == 0:
        raise ExportError("已找到 .prefab 文件 但均未包含 Unity YAML 头")

    packages_dir = project_dir / "Packages"
    settings_dir = project_dir / "ProjectSettings"
    inventory = {
        "prefab_count": len(prefabs),
        "unity_yaml_prefab_count": yaml_prefabs,
        "texture_count": counts["texture"],
        "material_count": counts["material"],
        "shader_count": counts["shader"],
        "script_count": counts["script"],
        "audio_count": counts["audio"],
        "asset_file_count": counts["asset_file"],
        "meta_file_count": counts["meta_file"],
        "asset_total_file_count": total_files,
        "has_packages_directory": packages_dir.is_dir(),
        "has_project_settings_directory": settings_dir.is_dir(),
        "package_files": list_project_files(packages_dir),
        "project_settings_files": list_project_files(settings_dir),
    }
    # Pack Data：SFS 把零件自己的贴图/音频以 byte[] 塞进 .asset，这里确认它们还在
    try:
        inventory["pack_data"] = scan_pack_data_payloads(assets_dir)
    except Exception:
        inventory["pack_data"] = {}
    return inventory


def write_export_manifest(project_dir: Path, input_path: Path, inventory: dict) -> None:
    """将资源类型统计写入工程根目录，便于确认贴图与配置文件是否导出。"""
    pack = inventory.get("pack_data") or {}
    audio_packs = int(pack.get("audio_pack_files", 0) or 0)
    texture_packs = int(pack.get("texture_pack_files", 0) or 0)
    audio_kinds = pack.get("audio_kinds") or {}
    kinds_text = ", ".join(f"{k}×{v}" for k, v in sorted(audio_kinds.items())) or "无"
    manifest = {
        "source_pack": input_path.name,
        "exporter": "sfs_project_exporter.py",
        "inventory": inventory,
        "notes": [
            "Assets 目录包含实际 Prefab 贴图 材质和其他可恢复资源",
            "请保留 .meta 文件 以维持导出项目内的 GUID 引用",
            "自定义脚本可能仍依赖原游戏程序集 因此不能保证能编译",
            f"音频 Pack Data 已保留 共 {audio_packs} 个 .asset 内含音频字节流（{kinds_text}）"
            " 音频以 byte[] 内嵌在 .asset 里 不会自动变成可播放的 .wav/.ogg 提取后才可试听",
        ],
    }
    (project_dir / "EXPORT_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    readme = f'''# SFS .pack 导出工程\n\n该目录由 `sfs_project_exporter.py` 从 `{input_path.name}` 导出 `Assets/` 下保存真实 Unity YAML Prefab 及其依赖资源\n\n| 资源类别 | 数量 |\n| --- | ---: |\n| Prefab | {inventory["prefab_count"]} |\n| 已验证 YAML Prefab | {inventory["unity_yaml_prefab_count"]} |\n| 贴图 | {inventory["texture_count"]} |\n| 材质 | {inventory["material_count"]} |\n| Shader | {inventory["shader_count"]} |\n| 脚本/程序集导出 | {inventory["script_count"]} |\n| 音频 | {inventory["audio_count"]} |\n| Unity `.asset` 文件 | {inventory["asset_file_count"]} |\n| `.meta` 文件 | {inventory["meta_file_count"]} |\n| 含音频字节流的 Pack Data `.asset` | {audio_packs} |\n| 含贴图字节流的 Pack Data `.asset` | {texture_packs} |\n\n`Packages/` {"已导出" if inventory["has_packages_directory"] else "未生成"} `ProjectSettings/` {"已导出" if inventory["has_project_settings_directory"] else "未生成"} 完整机器可读清单见 `EXPORT_MANIFEST.json`\n\n音频 Pack Data {kinds_text} SFS 把零件音频以 byte[] 内嵌在 `.asset` 里 文件已完整保留 但需提取字节才能变成可播放音频\n\n请使用 Unity Hub 打开此文件夹 或将整个 `Assets/` 复制至已有项目 不要省略 `.meta` 文件\n'''
    (project_dir / "EXPORT_README.md").write_text(readme, encoding="utf-8")


def validate_output_location(input_path: Path, output_dir: Path, zip_path: Path) -> None:
    if output_dir == input_path or input_path.is_relative_to(output_dir):
        raise ExportError(
            "工程输出目录不能是输入 .pack 所在目录或其上级目录"
            "请选择一个独立子文件夹 例如 Starship V3_UnityProject"
        )
    if zip_path == input_path:
        raise ExportError("输出 ZIP 不能与输入 .pack 使用同一路径")


def numbered_directory(path: Path) -> Path:
    candidate = path
    index = 2
    while candidate.exists() or Path(str(candidate) + ".zip").exists():
        candidate = path.parent / f"{path.name}_{index}"
        index += 1
    return candidate


def numbered_file(path: Path) -> Path:
    candidate = path
    index = 2
    while candidate.exists():
        # 直接用目录名 + 序号 + 原扩展名，避开模组名里含点号导致的 with_suffix 误删
        candidate = path.parent / f"{path.name.rsplit('.', 1)[0]}_{index}{path.suffix}"
        index += 1
    return candidate


def _dot_safe_zip(path: Path) -> Path:
    """返回 path 对应的 .zip 路径；模组名里含点号时 with_suffix 会误删，故此手动生成。"""
    return Path(str(path) + ".zip")


def export_prefabs(args: argparse.Namespace) -> None:
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.is_file():
        raise ExportError(f"输入 .pack 不存在 {input_path}")

    requested_output = Path(args.output_dir).expanduser().resolve()
    requested_zip = Path(args.zip).expanduser().resolve() if args.zip else None
    validate_output_location(input_path, requested_output, requested_zip or _dot_safe_zip(requested_output))
    output_dir = numbered_directory(requested_output)
    zip_path = numbered_file(requested_zip) if requested_zip else _dot_safe_zip(output_dir)
    if output_dir != requested_output:
        log(f"[*] 为保护已有文件 工程将导出到新目录 {output_dir}")
    if requested_zip and zip_path != requested_zip:
        log(f"[*] 为保护已有文件 ZIP 将保存为 {zip_path}")

    executable = resolve_asset_ripper(args.asset_ripper, auto_download=not args.no_download)
    log(f"[*] 使用 AssetRipper {executable}")

    with tempfile.TemporaryDirectory(prefix="sfs_prefab_export_") as temporary_directory:
        temporary = Path(temporary_directory)
        source_dir = temporary / "decoded_pack"
        export_root = temporary / "assetripper_export"
        log_path = temporary / "assetripper.log"
        decode_pack_resources(input_path, source_dir)

        port = unused_local_port()
        base_url = f"http://127.0.0.1:{port}"
        process = start_asset_ripper(executable, port, log_path)
        try:
            log("[*] 正在启动 AssetRipper...")
            try:
                wait_for_server(base_url, process, log_path)
            except AssetRipperExitError as exc:
                if has_unsupported_advanced_options(exc.log_path):
                    compatible_executable = executable
                    log("[!] 检测到旧版 AssetRipper 正在使用兼容参数重启")
                elif exc.returncode in ASSET_RIPPER_CRASH_CODES:
                    # 兼容版与本工具内置版同为 1.1.4：直接复用当前可执行文件，避免在应无网的环境里重新下载。
                    compatible_executable = executable
                    log(f"[!] 检测到已知 Windows 崩溃码 {exc.returncode} 改用兼容参数重启 复用内置版本 不联网下载")
                else:
                    raise
                stop_process(process)
                port = unused_local_port()
                base_url = f"http://127.0.0.1:{port}"
                log_path = temporary / "assetripper_compatibility.log"
                process = start_asset_ripper(compatible_executable, port, log_path, compatibility_mode=True)
                wait_for_server(base_url, process, log_path)
            log("[*] 正在加载解码后的 AssetBundle...")
            post_path(base_url, "/LoadFolder", source_dir)
            log("[*] 正在导出 Unity 工程与 Prefab 资源较多时请耐心等待 ...")
            export_root.mkdir(parents=True, exist_ok=True)
            post_path(base_url, "/Export/UnityProject", export_root)
        finally:
            stop_process(process)

        project_dir = export_root / "ExportedProject"
        if not project_dir.is_dir():
            log_copy = output_dir.parent / f"{output_dir.name}_assetripper.log"
            shutil.copy2(log_path, log_copy)
            raise ExportError(f"AssetRipper 未生成 ExportedProject 日志已复制到 {log_copy}")

        inventory = validate_project(project_dir)
        write_export_manifest(project_dir, input_path, inventory)
        shutil.copytree(project_dir, output_dir)
        # 确认 .asset（Pack Data 音频就在这些文件里）拷贝后一个不少
        src_assets = count_files(project_dir / "Assets", {".asset"})
        dst_assets = count_files(output_dir / "Assets", {".asset"})
        pack = inventory.get("pack_data") or {}
        audio_packs = int(pack.get("audio_pack_files", 0) or 0)
        if dst_assets < src_assets:
            log(f"[!] .asset 数量不一致 源 {src_assets} 目标 {dst_assets} 请检查磁盘空间或权限")
        else:
            log(f"[+] .asset 已保留 {dst_assets} 个 其中含音频字节流的 Pack Data {audio_packs} 个")
        log(
            f"[+] 已导出 {inventory['prefab_count']} 个 Prefab YAML {inventory['unity_yaml_prefab_count']}"
            f"贴图 {inventory['texture_count']} 材质 {inventory['material_count']}"
            f".meta {inventory['meta_file_count']}"
        )
        log(
            f"[+] 工程文件 Packages={'是' if inventory['has_packages_directory'] else '否'}"
            f"ProjectSettings={'是' if inventory['has_project_settings_directory'] else '否'}"
        )

    if not args.no_zip:
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        _base = str(zip_path)
        if _base.lower().endswith(".zip"):
            _base = _base[:-4]  # make_archive 会自动补 .zip，这里去掉避免 .zip.zip
        shutil.make_archive(_base, "zip", output_dir.parent, output_dir.name)
        log(f"[+] 已生成 ZIP {zip_path}")
    log(f"[✔] 完成 Unity 工程目录 {output_dir}")
    return output_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从 SFS .pack 一键导出真实 Unity Prefab 调用官方 AssetRipper",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("-i", "--input", required=True, help="原始 .pack 文件路径")
    parser.add_argument(
        "-o", "--output-dir", default="SFS_Prefab_Export",
        help="导出的 Unity 工程目录 默认 SFS_Prefab_Export",
    )
    parser.add_argument("--zip", help="输出 ZIP 文件路径 默认与 --output-dir 同名")
    parser.add_argument("--asset-ripper", help="AssetRipper.GUI.Free 或 .exe 可执行文件路径")
    parser.add_argument("--no-download", action="store_true", help="未找到 AssetRipper 时不自动从官方发布页下载")
    parser.add_argument("--no-zip", action="store_true", help="仅导出目录 不额外生成 ZIP")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖已有输出目录和 ZIP")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        export_prefabs(args)
        return 0
    except ExportError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n❌ 已取消", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
