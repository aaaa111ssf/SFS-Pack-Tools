#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SFS Pack Tool 的「无界面」内核层：常量、文案、纯函数，以及导出/并入的业务流程。

这个模块刻意不 import 任何 GUI 库：
  - `sfs_pack_tool_gui.py`（PyQt5 + SiliconUI 界面）和
  - `legacy/sfs_pack_tool_gui_tk.py`（旧 Tkinter 界面）
都从这里 import，业务逻辑只有一份，改一处两边都生效。

界面相关的东西（弹窗）通过 `set_ui_hooks()` 注入，未注入时退化为打印，
因此本模块可以被单元测试单独加载（test_core_smoke.py 就是这么用的）。
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import webbrowser

import UnityPy
import sfs_project_exporter as prefab_exporter
from sfs_official_keys import OFFICIAL_LOC_KEYS

DEFAULT_AUTHOR = "A Future star"
# 版本号的单一信息源。改版本时要同步：SFS_Pack_Tool.spec 的 name= 与注释、
# build.bat / build_and_sign.bat / sign.bat、APP_USER_MODEL_ID、tutorial.html。
VERSION = "2.3.6-PyQt"
VERSION_TITLE = "V2.3.6-PyQt"
EXCLUDE_WORDS = {
    "Color_Gray", "Toggle", "width", "target_state", "tank", "height", "DeployParachute",
    "Landing_Leg_Expanded", "Basic_Parts", "Color_Black", "Color_White", "Flat Smooth 4",
    "Flat Smooth", "Detach", "Flat Faces", "Liquid_Fuel", "Metal", "Panel_Expanded",
    "width_original", "Engine_2", "fairing", "mass", "Flat_Shadow", "Separation",
    "Expanded", "ToggleEnabled", "ToggleEngine", "cone", "Engines", "Nozzle_2",
    "Engine_Parts", "torque", "throttle", "Mass_Unit", "engine_on", "ToggleRCS",
    "ToggleTransfer", "Solid_Fuel",
}
# 承载可展示文本的叶字段名：标准扫描只收这些，天然避开内部变量名
DISPLAY_LEAF_FIELDS = {
    "DisplayName", "displayName", "Description", "description",
    "Author", "TranslatableName", "Text", "text", "Title", "title",
    "Label", "label", "Unit", "unit", "Units", "units",
}
# 深度扫描时排除的叶字段名（精确匹配末段）
INTERNAL_LEAF_FIELDS = {
    "m_MethodName", "m_ClassName", "m_Namespace", "m_TypeName", "m_Name", "m_Script",
    "variableName", "input", "output", "name", "id", "type", "key", "reference",
    "tag", "layer", "fragmentName", "saves", "points", "elements",
}
# 人工确认区标记键：深度扫描的疑似串放这里，绝不自动写回
CANDIDATES_KEY = "__CANDIDATES__"

BUILD_ORDER = ("AndroidBuild", "WindowsBuild", "MacBuild", "IOS_Build")
PLATFORM_KEYS = ("WindowsBuild", "AndroidBuild", "MacBuild", "IOS_Build")
PLATFORM_NAMES = {
    "WindowsBuild": "Windows",
    "AndroidBuild": "Android",
    "MacBuild": "Mac",
    "IOS_Build": "iOS",
}
TEXT = {
    "zh": {
        "window": "SFS Pack Tool V2.3.6-PyQt - Localization & Unity Export-by A Future star",
        "title": "SFS Pack Tool " + VERSION_TITLE,
        "subtitle": "汉化写入 · Prefab · 贴图 · Unity 工程导出 · 免挂提取",
        "language": "语言",
        "chinese": "中文",
        "english": "English",
        "input_frame": "输入文件",
        "tab_restore": "① 还原（导入工程）",
        "tab_translate": "② 汉化",
        "tab_strip": "③ 剥离",
        "tab_hint": "选 .pack 后在对应标签页里操作；切换标签页不会中断正在跑的任务。",
        "select_pack": "选择原始 mod.pack",
        "select_translation": "选择翻译 JSON",
        "no_pack": "尚未选择 mod.pack",
        "translation_none": "翻译 JSON：尚未选择",
        "translation_selected_label": "翻译 JSON：{name}",
        "log_title": "日志",
        "clear_log": "清空日志",
        "safety_frame": "保险与预览",
        "safety_hint": "导入前先预览会改哪些文件；导入后想撤销就一键回滚（回滚前会先把现状再备份一份）。",
        "preview_merge": "合并前预览",
        "restore_backup": "一键回滚…",
        "batch": "批量导出…",
        "batch_pick": "选择要批量导出的 .pack（可多选）",
        "batch_title": "批量导出",
        "batch_body": "成功 {ok} 个，失败 {failed} 个。\n详见日志窗口。",
        "batch_result": "[批量] 结果：成功 {ok} · 失败 {failed} · 跳过 {skipped}",
        "no_pack_first": "请先选择 mod.pack 与 Toolkit 工程。",
        "preview_need_dirs": "预览需要先选好 mod.pack 与 Modding Toolkit 工程。",
        "preview_start": "[预览] 正在比较合并包与 Toolkit 现状…",
        "preview_done": "[预览] 完成（未改动任何文件）",
        "preview_fail": "[预览] [!] {error}",
        "preview_title": "合并预览",
        "preview_body": "本次导入会新增 {add} 个文件、替换 {replace} 个、跳过 {skip} 个。\n新部件 {parts_added} 个。\n\n详见日志窗口。",
        "restore_title": "一键回滚",
        "restore_hint": "选择一条备份还原到 Toolkit。默认只预演，确认后才真正写入；回滚前会把现状再备份一份。",
        "restore_none": "这个 Toolkit 里没有找到备份。（_PackToolBackup 为空）",
        "restore_pick": "选择要回滚到的备份：",
        "restore_dryrun": "先预演（不写入）",
        "restore_apply": "确认回滚",
        "restore_log_dry": "[回滚] 预演完成：将还原 {n} 个文件。点「确认回滚」才会真正写入。",
        "restore_log_done": "[回滚] 已完成：还原 {n} 个文件，跳过 {skip} 个。",
        "restore_fail": "[回滚] [!] {error}",
        "log_dir_missing": "日志目录还不存在：{path}",
        "probe_log": "[探测] Unity {unity} · Toolkit {toolkit} · 脚本 {files} 个 · 指纹 {fp}",
        "probe_fail": "[探测] [!] {error}",
        "probe_title": "Toolkit 版本探测",
        "probe_body": "Unity 版本：{unity}\nToolkit 版本：{toolkit}\n脚本文件：{files} 个\n指纹：{fp}\n\n把这份信息和 mod.pack 一起发给作者，能快速判断版本是否匹配。",
        "incremental": "增量导出（包与 Toolkit 未变时跳过）",
        "incremental_skip": "[增量] 跳过导出：{reason}",
        "incremental_skip_hint": "[增量] 取消勾选「增量导出」可强制重跑。",
        "incremental_full": "[增量] 全量导出：{reason}",
        "incremental_check_fail": "[增量] [!] 判断失败（按全量继续）{error}",
        "incremental_recorded": "[增量] 已记录本次导出（{n} 个部件）供下次判断",
        "incremental_record_fail": "[增量] [!] 记录失败 {error}",
        # ---- 设置页（菜单栏「设置」）----
        "menu_settings": "设置",
        "menu_settings_open": "打开设置（AssetRipper 版本 / 日志 / 高级）",
        "settings_title": "设置",
        "settings_hint": "改完点「应用」才生效；点「取消」或直接关窗不会保存任何改动。",
        "settings_section_ripper": "AssetRipper",
        "settings_ripper_mode": "使用哪一版 AssetRipper：",
        "settings_ripper_bundled": "内置版（推荐，随工具打包）",
        "settings_ripper_version": "指定版本（自动下载/复用缓存）",
        "settings_ripper_custom": "手动指定可执行文件",
        "settings_ripper_ver_label": "版本号（如 1.1.4 / 1.0.1）：",
        "settings_ripper_path_label": "可执行文件路径：",
        "settings_ripper_note": "内置版反编译效果不好时才需要换版本。指定版本会跳过内置版、优先用已下载的缓存（下次导出时才真正下载，不在设置页联网）。",
        "settings_section_log": "日志",
        "settings_log_dir_label": "日志目录：",
        "settings_open_log_dir": "打开日志目录",
        "settings_keep_days": "日志保留天数：",
        "settings_section_adv": "高级",
        "settings_incremental": "增量导出（包与 Toolkit 都未变时跳过重复导出）",
        "settings_repair_engine_17": "实验：1.7 引擎自动修复（未发布，仅测试用）",
        "repair17_skip": "[1.7修复] 目标 Toolkit 不是 1.7 推进重构版，已跳过",
        "repair17_fail": "[1.7修复] [!] 失败 {exc}",
        "settings_probe": "探测当前 Toolkit 版本",
        "settings_apply": "应用",
        "settings_cancel": "取消",
        "settings_saved": "[设置] 已应用：{summary}",
        "settings_ripper_summary_bundled": "AssetRipper 用内置版",
        "settings_ripper_summary_version": "AssetRipper 指定版本 {version}",
        "settings_ripper_summary_custom": "AssetRipper 用 {path}",
        "settings_ripper_need_version": "选了「指定版本」就必须填版本号。",
        "settings_ripper_bad_version": "版本号只能由数字和点组成（如 1.1.4）。",
        "settings_ripper_need_path": "选了「手动指定」就必须填可执行文件路径。",
        "settings_ripper_bad_path": "这个路径下没有可执行文件：{path}",
        "settings_keep_days_bad": "日志保留天数必须是 1~3650 的整数。",
        "clear_cache": "清理缓存",
        "cache_title": "缓存清理",
        "cache_hint": "勾选要清理的项目后点「立即清理」。带 ★ 的是重要数据（清理后不可恢复）。",
        "cache_item_stage": "导出暂存目录（下次导出会重建）",
        "cache_item_tmp": "导出临时残留（异常中断遗留）",
        "cache_item_ripper": "AssetRipper 下载缓存（下次导出会重新解压）",
        "cache_item_dedupe": "工程去重备份（导出目录内）",
        "cache_item_backup": "★ Toolkit 备份目录（合并/修复前的保险）",
        "cache_item_dist": "★ 历史 EXE 备份（dist/_backup）",
        "cache_scan_none": "没有发现可清理的缓存。",
        "cache_confirm": "即将清理 {n} 项，共 {size}。确认继续？",
        "cache_done": "缓存清理完成：释放 {size}",
        "cache_busy": "有任务在运行，请等它完成再清理缓存。",
        "cache_none_selected": "请至少勾选一项。",
        "progress_idle": "空闲",
        "progress_export": "一键导出",
        "progress_strip": "剥离平台",
        "progress_analyze": "读取包信息",
        "progress_extract": "提取文本",
        "progress_write": "写入翻译",
        "progress_cache": "清理缓存",
        "progress_batch": "批量导出",
        "progress_preview": "合并预览",
        "progress_probe": "版本探测",
        "busy_running": "⏳ {name} 进行中…（界面操作已临时锁定）",
        "progress_step_scan": "扫描包信息…",
        "progress_step_ripper": "AssetRipper 导出工程…",
        "progress_step_align": "脚本免挂对齐…",
        "progress_step_shader": "修复空壳着色器…",
        "progress_step_dedupe": "工程去重…",
        "progress_step_merge": "生成合并包…",
        "progress_step_packdata": "并入 Toolkit + PackData…",
        "progress_step_strip_trim": "剔除多余平台…",
        "progress_step_strip_write": "写出 .pack…",
        "translator_frame": "汉化处理",
        "author": "汉化作者标识",
        "extract": "提取待翻译文本",
        "extract_path": "提取 JSON 保存路径",
        "select_json_path": "选择保存位置",
        "write": "写入汉化并生成 Pack",
        "export_frame": "Unity Prefab / 贴图 / 工程导出",
        "builtin_ripper_hint": "使用内置 AssetRipper 随工具打包 无需手动选择或下载",
        "export": "一键导出工程",
        "ready": "请选择pack文件",
        "select_pack_first": "请先选择原始 mod.pack",
        "no_pack_title": "未选择文件",
        "export_start": "开始导出",
        "toolkit_dir": "Modding Toolkit 工程路径",
        "select_toolkit": "选择 Toolkit",
        "toolkit_hint": "必填 部件会直接导出并合并进这个 Modding Toolkit 只新增 Toolkit 里没有的部件 已有部件自动跳过 导出会先在临时目录中转 完成后把新部件写进 Toolkit 的 Assets",
        "selected_toolkit": "已选择 Toolkit {path}",
        "installed_to_toolkit": "✔ 已完成 新增部件已合并进 Toolkit 新增 {new} 个 跳过已有 {skip} 个 拷贝资产 {copy} 个文件 打开 Toolkit 的 Assets/Resources/Parts/{sub} 即可看到并编辑",
        "need_toolkit": "需要 Modding Toolkit 路径",
        "need_toolkit_text": "导出前必须先选择有效的 Modding Toolkit 工程路径\n理由 导出的部件 prefab 引用的游戏脚本需要 Toolkit 提供 不填则部件会断链/无法编辑\n请点击 选择 Toolkit 并选中含 Assets\\Scripts 的 Toolkit 工程根目录",
        "need_toolkit_invalid": "Modding Toolkit 路径无效",
        "toolkit_root_fixed": "[TK] 所选目录不是 Toolkit 工程根 已自动上溯到 {path}",
        "need_toolkit_invalid_text": "所选目录不是有效的 Toolkit 工程 未在 Assets\\Scripts 下找到 .cs.meta 脚本\n请选择官方 Modding Toolkit 的工程根目录 内含 Assets\\Scripts\\Assembly-CSharp 等",
        "export_done": "✔ Unity 工程导出完成 请查看输出目录及同名 ZIP",
        "export_failed": "❌ Unity 工程导出失败 {error}",
        "export_busy": "⏳ 已有导出任务在进行 请等它完成再点",
        "export_running": "导出中",
        "install_opt": "导出后并入 Toolkit 不覆盖已有文件",
        "install_skipped_opt": "[安装] 未勾选 并入 Toolkit 合并包已生成 可自行按 MERGE_README.md 拷入",
        "install_refused": "[安装] [!] 检出 {n} 处 GUID 冲突 已取消写入 Toolkit 请先查看合并包里的 MERGE_README.md 人工核对",
        "install_skipped": "[安装] 已跳过 {n} 个 Toolkit 中已存在的文件 未覆盖任何既有内容",
        "install_failed": "[安装] 写入 Toolkit 失败 {error}",
        "shader_fixed": "[着色器] 已自动修复 {n} 个 AssetRipper 空壳着色器(零件渲成黑板的根因) 换成 Toolkit 真着色器源码",
        "shader_unmatched": "[着色器] [!] 还有 {n} 个着色器在 Toolkit 里找不到同名真身 {names}",
        "install_repaired": "[安装] 修复 {name} 悬空引用 {before} 处 -> {after} 处",
        "install_wrote_parts": "[安装] 已把 {n} 个新增部件并入 Toolkit {path}",
        "install_wrote_files": "[安装] 已写入 {n} 个文件 无新增 prefab {path}",
        "install_nothing": "[安装] 没有新文件需要写入 Toolkit",
        "install_replaced_stale": "[安装] 已替换 {n} 个 GUID 过期的同名残留(上一轮导入留下的旧版本占位 会让贴图/材质挂空) 原文件已备份到 {path}",
        "install_repair_done": "[安装] 已修复 {n} 个引用悬空的既有资产 原文件已备份到 {path}",
        "install_asm_conflict": "[安装] [!] 拒绝并入 Toolkit：已有内容不同的同名程序集 {names}（一个文件都没写）详见下方弹窗",
        "install_asm_conflict_item": "[安装] [!] 程序集 {name}（{rel}）已被占用：Toolkit 里是 {old_owner} 的程序集（guid {old_guid}），本次要装的是 {new_owner} 的（guid {new_guid}）",
        "install_asm_conflict_scan_fail": "[安装] [!] 同名程序集预检失败（{error}）已保守拒绝并入 以免顶掉 Toolkit 里已有的程序集 请重试或反馈",
        "install_src_conflict": "[安装] [!] 拒绝并入 Toolkit：本次的源码与 Toolkit 里已有的脚本撞了同名类型（CS0101 会让整个模组加载不了）详见下方弹窗",
        "install_src_conflict_item": "[安装] [!] 类型 {type} 被定义了两次：本次 {incoming} ↔ 既有 {existing}",
        "install_src_conflict_scan_fail": "[安装] [!] 源码撞名预检失败（{error}）已放行并入 本次无法排除 CS0101 风险 请在 Unity 里确认脚本能编译过",
        "install_src_conflict_title": "源码类型撞名 会报 CS0101 已拒绝合并",
        "install_src_conflict_body": "本次要并入的源码里，有类型名和 Toolkit 里已有的脚本撞了。Unity 会把这些 .cs 一起编译进同一个程序集，于是报 **CS0101 类型重复定义**，整个模组加载不了。\n\n{list}\n\n怎么办：\n• 如果两边其实是同一个模组（重复导入），删掉 Toolkit 里旧的那份 .cs 再导入即可。\n• 如果是两个不同的模组：一份 Toolkit 的同一个程序集里放不下两份同名类型，请让其中一个模组作者改类名，或把其中一个模组的自定义脚本改成 dll 方式提供。\n• 注意这只查源码（.cs）。两个 **dll** 里的同名类型不会报 CS0101（预编译程序集各自独立），所以工具不拦那种情况。\n\n合并包仍在原处：{path}",
        "install_asm_conflict_title": "同名程序集冲突 已拒绝合并",
        "install_asm_conflict_scan_fail_body": "工具没能完成「同名程序集」预检（原因见日志），已保守拒绝把合并包并入 Toolkit，一个文件都没写。\n\n注意：这**不是**发现了冲突，而是预检自己判不准。这道预检防的是「后装的模组把 Toolkit 里已有的程序集静默顶掉、让先装模组的部件脚本全部 missing script」。判不准时宁可停下报错，也不放行去赌一把。\n\n请重试一次；若仍失败，请把日志里那条错误连同本弹窗一起反馈。\n\n合并包仍在原处，可自行处理：{path}",
        "install_asm_conflict_body": "Toolkit 里已经有**内容不同**的同名程序集，已拒绝把本次合并包并进去（一个文件都没写）。\n\n{list}\n\n程序集文件名不能改：Unity 的 MonoScript 里 m_AssemblyName 就是它，改了 Unity 就认不出里面的类。两个模组的 dll 撞名时只有先装的能保住，继续导入会让先装那个模组的部件脚本全部 missing script。\n\n怎么办：\n• 一份 Toolkit 目前只放得下一份 mod 程序集。要同时用两个带自定义脚本的模组，请自行把两份 dll 合成一份（第二个 dll 里的类要改名，否则 Unity 报 CS0101 类型重复定义），再走本工具导入。\n• 只想用一个：把先装那个模组的部件 prefab 与 Assets/Plugins 下的 dll 及 .meta 删干净，再导入本模组。\n• 如果这两份 dll 其实来自同一个模组，说明文件被改动过，请人工核对后再导入。\n\n合并包仍在原处，可自行处理：{path}",
        "packdata_done": "[PackData] 已自动生成 PackData 资产 {path} 并统一 {labeled} 个资产标签 {label} Unity 里 SFS→打包模组包 选资产+标签即可出包",
        "packdata_fail": "[PackData] [!] 自动生成失败 {error} 可在 Unity 手动创建",
        "packdata_skipped_refused": "[PackData] 并入被拒 未生成 PackData 资产(Toolkit 里还没有这个模组的任何东西 盖了也是空入口)",
        "log_dedupe_fail": "[去重] [!] 工程内去重失败 {exc}",
        "repair_start": "开始清理 Toolkit 里残留的 AssetRipper 空壳着色器(零件渲成黑板的根因)...",
        "repair_done": "[修复] 已删除 {stubs} 个空壳着色器 重写 {refs} 处材质引用 同步 {names} 个资产名 备份于 {backup}",
        "repair_none": "[修复] 没发现空壳着色器 Toolkit 已是干净的",
        "repair_dangling_none": "[悬空] 未发现悬空引用 Toolkit 已是干净的",
        "repair_dangling_scan": "[悬空] 扫描到 {n} 处悬空引用",
        "repair_dangling_redirected": "[悬空] 已按同名重定向 {n} 处",
        "repair_dangling_imported": "[悬空] 已补入 Toolkit 缺失资产 {m} 个：{names}",
        "repair_dangling_unresolved": "[悬空] 无法自动修复 {n} 处 清单见 {path}",
        "repair_dangling_nopkg": "[悬空] 未提供原始 mod 工程目录 仅扫描+清单 如需自动修复请填写原始 mod 工程目录",
        "repair_dangling_clean": "[修复] 悬空引用：重定向 {redirected} 处 补入 {imported} 个 未解决 {unresolved} 处",
        "select_package": "选择",
        "selected_pack": "已选择源文件 {name}",
        "selected_translation": "已选择翻译文件 {name}",
        "extract_start": "开始提取文本...",
        "no_pack_log": "❌ 未选择 mod.pack",
        "json_error": "❌ JSON 读取错误 {error}",
        "scan": "  扫描 {build}...",
        "unpack_error": "  ❌ {build} 解包失败 {error}",
        "extract_done": "✔ 提取完成 共 {count} 条文本 → {path}",
        "no_translation": "❌ 未选择翻译 JSON",
        "read_failed": "❌ 文件读取失败 {error}",
        "writing": "正在写入 {build}...",
        "decode_failed": "  ❌ {build} 解码失败 {error}",
        "write_done": "  ✔ {build} 完成 修改 {count} 处",
        "save_failed": "  ❌ {build} 保存失败 {error}",
        "pack_done": "✔ 最终文件已生成 {path}",
        "output_failed": "❌ 输出失败 {error}",
        "processing_failed": "❌ 处理失败 {error}",
        "strip_frame": "剥离 / 精简工具",
        "strip_hint": "剥离 = 只保留勾选平台的 Build 与 CodeAssembly 删除其他平台 大幅减小 .pack 体积\n剥离前会先扫描包信息 确保结果至少保留一个平台",
        "target_platform": "保留平台(可多选)",
        "select_strip_output": "输出位置",
        "pick_strip_output": "选择位置",
        "analyze": "包信息",
        "strip": "剥离到所选平台",
        "strip_scan_header": "[剥离] 已扫描包信息 包内平台 {builds} 个：{list}",
        "strip_scan_plat": "    {plat} {size}",
        "strip_missing_warn": "[剥离] [!] 所选平台 {missing} 不在包内 已忽略 只保留 {kept}",
        "strip_no_target": "❌ 所选平台 {wanted} 都不在此 .pack 里 包内平台：{present} 无法剥离 请先用 包信息 确认",
        "strip_none_selected": "❌ 请至少勾选一个要保留的平台",
        "analyzing": "正在分析包信息...",
        "pack_size": "  包文件 {content} ({size})",
        "assembly": "    CodeAssembly {size}",
        "assembly_absent": "    CodeAssembly 未包含",
        "build_present": "    {plat} 解压后约 {size} {parts} 个部件",
        "build_absent": "   {plat} 未包含",
        "analyze_done": "✔ 包信息完成 共 {builds} 个平台 {parts} 个部件 解压共 {total}",
        "strip_output_is_input": "❌ 剥离输出不能就是源 .pack 会直接覆盖原模组 请另选一个路径",
        "strip_output_set": "剥离输出 {path}",
        "strip_no_pack": "❌ 未选择 mod.pack",
        "strip_no_output": "❌ 未设置输出位置 已在原目录生成",
        "strip_start": "开始剥离...",
        "strip_read_fail": "❌ 读取 .pack 失败 {error}",
        "strip_removed": "  删除 {plat}",
        "strip_keep": "  保留 {plat}",
        "strip_done": "✔ 剥离完成 {out} {size}",
        "strip_fail": "❌ 剥离失败 {error}",
        "menu_tutorial": "教程",
        "menu_tutorial_open": "打开使用教程 (HTML)",
        "menu_author": "关于作者",
        "menu_author_open": "作者与 QQ 群",
        "menu_about": "关于应用",
        "menu_about_open": "工具介绍 / 实现原理",
        "about_app_title": "关于 SFS Pack Tool",
        "about_author_title": "关于作者",
        "about_close": "关闭",
        "link_qq": "点击加入 QQ 群【𝔸𝔽𝕊 ℍ𝕦𝕓】",
        "qq_hint": "QQ 群号 923038827",
        "log_align_done": "[免挂] 完成 重写 {rewritten} 个 prefab/asset {refs} 处脚本引用",
        "log_align_skip": "[免挂] 未执行 {error}",
        "log_align_fail": "[免挂] 对齐失败 不影响已导出的工程 {exc}",
        "log_scan_fail": "包信息扫描失败 {exc}",
        "scan_unreliable_title": "自定义类判定不可靠",
        "scan_unreliable_log": "[扫描] [!] 自定义类判定不可靠（{reason}）已退化为「{source}」口径 后续自动修复可能不完整",
        "scan_unreliable_body": "这个模组的自定义脚本类**没能可靠判定**，本次导出已改用「{source}」这种保守口径。\n\n原因：{reason}\n\n为什么必须告诉你：这份口径会把「Toolkit 里查不到的原版类」也算成 mod 自定义类。工具本身会按「拿不准就不动」处理（不会因此删错东西），但你看到的「自定义类 N 个」这个数字不可信，后续的自动修复也可能不完整。\n\n常见于 Toolkit 版本与 mod 作者用的不一致，或这个模组的包结构比较特殊。可以先照常导出；若导出后发现脚本挂空，请优先怀疑这一条，而不是反复重导。",
        "scan_ilspy_title": "未安装 ILSpy 看不到自定义脚本源码",
        "scan_ilspy_body": "这个模组带自定义脚本，但没找到反编译工具 ilspycmd，已跳过自动反编译。\n\n这**不影响**导入和出包（自定义脚本照样由 mod 自带的 dll 提供），只是你看不到源码。\n\n想查看/修改这些自定义脚本，二选一：\n• 装 ILSpy 命令行：dotnet tool install -g ilspycmd（装完重开本工具）\n• 或用 dnSpy 手动反编译 Assets/Plugins/ 下那个 dll",
        "log_organize_skip": "模组资产整理跳过 {error}",
        "log_organize_fail": "模组资产整理失败 {exc}",
        "log_shader_fail_export": "[着色器] 处理失败 不影响已导出的工程 {exc}",
        "log_merge_done": "[合并] 纯新增合并包 {pkg} 新增部件 {new} 跳过已有 {skip} 拷贝资产 {copy}",
        "log_merge_none": "[合并] 未生成 {error}",
        "log_merge_fail": "[合并] 生成失败 不影响已导出的工程 {exc}",
        "log_verify_hit": "[校验] 导出工程脚本引用 命中 {hit}/{total} 缺失 {miss}",
        "log_verify_missing": "[校验] [!] {n} 个 prefab 存在缺失脚本引用 {files}",
        "log_verify_fail": "[校验] 自检脚本引用失败 不影响导出结果 {exc}",
        "log_gate_blocked": "[闸门] [!!] 仍有 {n} 个脚本 GUID 找不到对应脚本 共 {refs} 处引用会挂空",
        "log_gate_stop": "[闸门] [!!] 已拒绝合并进 Toolkit 免得把挂空的 prefab 灌进去 详见 {path}",
        "log_gate_classes": "[闸门] [!!] 未接上的类 {classes}",
        "log_gate_title": "脚本没接上 已拒绝合并",
        "log_gate_body": "导出工程里还有 {n} 个脚本引用没接上（共 {refs} 处）。\n\n未接上的类：\n{classes}\n\n带着它们合并进 Toolkit，Unity 里会满屏 Script is missing。\n工具已停止合并，并生成排查清单：\n{path}\n\n最常见原因是 Toolkit 版本与 mod 作者用的不一致。",
        "tutorial_missing": "未找到 tutorial.html 请确认它与本程序在同一目录",
        "about_app_text": "SFS Pack Tool 是一站式 mod 工具，覆盖：\n• 汉化：提取/写入 mod.pack 的可翻译文本\n• Prefab 导出：用内置 AssetRipper 把 .pack 反编译成 Unity 工程\n• 免挂对齐：自动把 AssetRipper 占位脚本换成 Toolkit 真源码\n• 空壳着色器修复：把导致「黑板」的占位着色器换成真着色器\n• 悬空引用自愈：按同名/同 GUID 修复或补入缺失资产\n• 合并包：只裁剪 Toolkit 没有的新内容，安全并入\n\n实现上：导出时在系统临时目录中转，优先 copy 模式换真着色器源码(保留 GUID)，再按类名重写脚本 GUID 映射，最后做 GUID 冲突预检。",
        "about_author_text": "作者：A Future star\n本工具由 A Future star 开发并维护，用于降低 SFS mod 制作门槛。\n如有问题或建议，欢迎加入 QQ 群交流。",
    },
    "en": {
        "window": "SFS Pack Tool V2.3.6-PyQt - Localization & Unity Export-by A Future star",
        "title": "SFS Pack Tool " + VERSION_TITLE,
        "subtitle": "Localization · Prefab · Textures · Unity Export · Keep-alive extraction",
        "language": "Language:",
        "chinese": "中文",
        "english": "English",
        "input_frame": "Input Files",
        "tab_restore": "1. Restore (import)",
        "tab_translate": "2. Localization",
        "tab_strip": "3. Strip",
        "tab_hint": "Pick a .pack, then work in the matching tab; switching tabs never interrupts a running task.",
        "select_pack": "Select mod.pack",
        "select_translation": "Select translation",
        "no_pack": "No mod.pack selected",
        "translation_none": "Translation JSON: none selected",
        "translation_selected_label": "Translation JSON: {name}",
        "log_title": "Log",
        "clear_log": "Clear log",
        "safety_frame": "Safety & Preview",
        "safety_hint": "Preview what will change before importing; roll back any import afterwards (the current state is backed up first).",
        "preview_merge": "Preview merge",
        "restore_backup": "Roll back...",
        "batch": "Batch export...",
        "batch_pick": "Select .pack files to export in batch (multi-select)",
        "batch_title": "Batch export",
        "batch_body": "{ok} succeeded, {failed} failed.\nSee the log window for details.",
        "batch_result": "[Batch] Result: {ok} ok, {failed} failed, {skipped} skipped",
        "no_pack_first": "Select a mod.pack and a Toolkit project first.",
        "preview_need_dirs": "Preview needs both a mod.pack and a Modding Toolkit project.",
        "preview_start": "[Preview] Comparing merge package against the Toolkit...",
        "preview_done": "[Preview] Done (nothing was modified)",
        "preview_fail": "[Preview] [!] {error}",
        "preview_title": "Merge preview",
        "preview_body": "This import would add {add} files, replace {replace} and skip {skip}.\nNew parts: {parts_added}.\n\nSee the log window for details.",
        "restore_title": "Roll back",
        "restore_hint": "Pick a backup to restore into the Toolkit. It only previews by default; writing happens after you confirm, and the current state is backed up first.",
        "restore_none": "No backups found in this Toolkit (_PackToolBackup is empty).",
        "restore_pick": "Restore which backup:",
        "restore_dryrun": "Preview only",
        "restore_apply": "Confirm rollback",
        "restore_log_dry": "[Rollback] Preview done: {n} files would be restored. Click Confirm to actually write.",
        "restore_log_done": "[Rollback] Done: {n} files restored, {skip} skipped.",
        "restore_fail": "[Rollback] [!] {error}",
        "log_dir_missing": "Log folder does not exist yet: {path}",
        "probe_log": "[Probe] Unity {unity} · Toolkit {toolkit} · {files} scripts · fingerprint {fp}",
        "probe_fail": "[Probe] [!] {error}",
        "probe_title": "Toolkit version probe",
        "probe_body": "Unity version: {unity}\nToolkit version: {toolkit}\nScript files: {files}\nFingerprint: {fp}\n\nSend this together with the mod.pack name to the author to check version compatibility quickly.",
        "incremental": "Incremental export (skip when pack & Toolkit unchanged)",
        "incremental_skip": "[Incremental] Skipped export: {reason}",
        "incremental_skip_hint": "[Incremental] Untick \"Incremental export\" to force a full run.",
        "incremental_full": "[Incremental] Full export: {reason}",
        "incremental_check_fail": "[Incremental] [!] Check failed (continuing as full) {error}",
        "incremental_recorded": "[Incremental] Recorded this export ({n} parts) for next time",
        "incremental_record_fail": "[Incremental] [!] Record failed {error}",
        "menu_settings": "Settings",
        "menu_settings_open": "Open settings (AssetRipper version / logs / advanced)",
        "settings_title": "Settings",
        "settings_hint": "Click Apply to make changes take effect; Cancel or closing the window saves nothing.",
        "settings_section_ripper": "AssetRipper",
        "settings_ripper_mode": "Which AssetRipper to use:",
        "settings_ripper_bundled": "Bundled (recommended, ships with the tool)",
        "settings_ripper_version": "Specific version (download / reuse cache)",
        "settings_ripper_custom": "Pick an executable manually",
        "settings_ripper_ver_label": "Version (e.g. 1.1.4 / 1.0.1):",
        "settings_ripper_path_label": "Executable path:",
        "settings_ripper_note": "Only switch versions when the bundled one decompiles poorly. A specific version skips the bundled build and prefers the downloaded cache (the actual download happens on the next export, not here).",
        "settings_section_log": "Logs",
        "settings_log_dir_label": "Log folder:",
        "settings_open_log_dir": "Open log folder",
        "settings_keep_days": "Keep logs for (days):",
        "settings_section_adv": "Advanced",
        "settings_incremental": "Incremental export (skip when pack and Toolkit are unchanged)",
        "settings_repair_engine_17": "Experimental: 1.7 engine auto-repair (unreleased, testing only)",
        "repair17_skip": "[1.7 repair] Target Toolkit is not the 1.7 propulsion rebase; skipped",
        "repair17_fail": "[1.7 repair] [!] Failed: {exc}",
        "settings_probe": "Probe the current Toolkit version",
        "settings_apply": "Apply",
        "settings_cancel": "Cancel",
        "settings_saved": "[Settings] Applied: {summary}",
        "settings_ripper_summary_bundled": "AssetRipper uses the bundled build",
        "settings_ripper_summary_version": "AssetRipper pinned to version {version}",
        "settings_ripper_summary_custom": "AssetRipper uses {path}",
        "settings_ripper_need_version": "A version number is required for \"Specific version\".",
        "settings_ripper_bad_version": "Version may only contain digits and dots (e.g. 1.1.4).",
        "settings_ripper_need_path": "A path is required for \"Pick an executable\".",
        "settings_ripper_bad_path": "No executable found at: {path}",
        "settings_keep_days_bad": "Keep-days must be an integer between 1 and 3650.",
        "clear_cache": "Clear cache",
        "cache_title": "Cache cleanup",
        "cache_hint": "Tick the items to remove, then click Clear. Items marked ★ hold important data (not recoverable).",
        "cache_item_stage": "Export staging dir (rebuilt on next export)",
        "cache_item_tmp": "Leftover temp exports (from interrupted runs)",
        "cache_item_ripper": "AssetRipper download cache (re-extracted on next export)",
        "cache_item_dedupe": "In-project dedupe backups (inside export dirs)",
        "cache_item_backup": "★ Toolkit backup dir (safety net before merge/repair)",
        "cache_item_dist": "★ Historical EXE backups (dist/_backup)",
        "cache_scan_none": "No cache found.",
        "cache_confirm": "Remove {n} item(s), freeing {size}. Continue?",
        "cache_done": "Cache cleaned: freed {size}",
        "cache_busy": "A task is running; wait for it to finish before clearing the cache.",
        "cache_none_selected": "Tick at least one item.",
        "progress_idle": "Idle",
        "progress_export": "Quick Export",
        "progress_strip": "Strip Platforms",
        "progress_analyze": "Pack Info",
        "progress_extract": "Extract Text",
        "progress_write": "Write Translation",
        "progress_cache": "Clear Cache",
        "progress_batch": "Batch Export",
        "progress_preview": "Merge Preview",
        "progress_probe": "Version Probe",
        "busy_running": "{name} is running... (UI temporarily locked)",
        "progress_step_scan": "Scanning pack info...",
        "progress_step_ripper": "Exporting project via AssetRipper...",
        "progress_step_align": "Aligning scripts to Toolkit...",
        "progress_step_shader": "Fixing stub shaders...",
        "progress_step_dedupe": "Deduping project assets...",
        "progress_step_merge": "Building merge package...",
        "progress_step_packdata": "Merging into Toolkit + PackData...",
        "progress_step_strip_trim": "Dropping unwanted platforms...",
        "progress_step_strip_write": "Writing .pack...",
        "translator_frame": "Localization",
        "author": "Translator signature:",
        "extract": "Extract translatable text",
        "extract_path": "Extracted JSON save path:",
        "select_json_path": "Browse...",
        "write": "Apply translation and create Pack",
        "export_frame": "Unity Prefab / Texture / Project Export",
        "builtin_ripper_hint": "Uses the built-in AssetRipper (bundled with the tool); no manual selection or download needed.",
        "export": "Quick Export",
        "ready": "Ready. Select a mod.pack; export includes Prefabs, textures, materials, .meta files and Unity project files.",
        "select_pack_first": "Select the source mod.pack first.",
        "no_pack_title": "No input file",
        "export_start": "Starting Unity project export. The output includes Prefabs, textures, materials, .meta files, Packages and ProjectSettings.",
        "export_done": "✔ Unity project export completed. Check the output directory and its ZIP file.",
        "export_failed": "❌ Unity project export failed: {error}",
        "export_busy": "A export task is already running; please wait for it to finish.",
        "export_running": "Exporting...",
        "install_opt": "Merge into Toolkit after export (never overwrite existing files)",
        "install_skipped_opt": "[Install] Not enabled; the merge package is ready, copy it in manually per MERGE_README.md.",
        "install_refused": "[Install] [!] {n} GUID collisions found; cancelled writing into the Toolkit. Check MERGE_README.md first.",
        "install_skipped": "[Install] Skipped {n} files that already exist in the Toolkit (nothing overwritten).",
        "shader_fixed": "[Shader] Auto-fixed {n} AssetRipper stub shaders (the cause of black parts) with real Toolkit shader sources.",
        "shader_unmatched": "[Shader] [!] {n} shaders have no same-named counterpart in the Toolkit: {names}",
        "install_repaired": "[Install] Repaired {name}: dangling refs {before} -> {after}",
        "install_wrote_parts": "[Install] Merged {n} new parts into the Toolkit at {path}",
        "install_wrote_files": "[Install] Wrote {n} files (no new prefabs) at {path}",
        "install_nothing": "[Install] No new files need to be written to the Toolkit",
        "install_replaced_stale": "[Install] Replaced {n} same-named leftovers with stale GUIDs (old versions occupying the slot cause missing textures/materials); originals backed up to {path}",
        "install_repair_done": "[Install] Repaired {n} existing assets with dangling refs; originals backed up to {path}",
        "install_asm_conflict": "[Install] [!] Refused to merge into the Toolkit: same-named assemblies with different content already exist ({names}); nothing was written. See the popup below.",
        "install_asm_conflict_item": "[Install] [!] Assembly {name} ({rel}) is taken: the Toolkit has {old_owner}'s copy (guid {old_guid}), this import brings {new_owner}'s (guid {new_guid})",
        "install_asm_conflict_scan_fail": "[Install] [!] Same-named assembly pre-check failed ({error}); the merge was refused to avoid overwriting an assembly already in the Toolkit. Retry or report this.",
        "install_src_conflict": "[Install] [!] Refused to merge into the Toolkit: the incoming sources define a type that the Toolkit's scripts already define (CS0101 would stop the whole mod from loading). See the popup below.",
        "install_src_conflict_item": "[Install] [!] Type {type} is defined twice: incoming {incoming} vs existing {existing}",
        "install_src_conflict_scan_fail": "[Install] [!] Source clash pre-check failed ({error}); the merge continued, so CS0101 cannot be ruled out this time. Please confirm your scripts compile in Unity.",
        "install_src_conflict_title": "Duplicate type in sources - would cause CS0101, merge refused",
        "install_src_conflict_body": "Some types in the incoming sources already exist in the Toolkit's scripts. Unity compiles all of these .cs into the same assembly, so it reports **CS0101 duplicate type definition** and the whole mod fails to load.\n\n{list}\n\nWhat to do:\n- If both sides are really the same mod (re-import), delete the older .cs in the Toolkit and import again.\n- If they are two different mods: one assembly cannot hold two types with the same name, so ask one mod author to rename the class, or have that mod ship its custom scripts as a dll instead.\n- Note this only checks sources (.cs). Two **dlls** with the same type name do NOT cause CS0101 (precompiled assemblies are independent), so the tool does not block that case.\n\nThe merge package is still at: {path}",
        "install_asm_conflict_title": "Assembly name conflict - merge refused",
        "install_asm_conflict_scan_fail_body": "The tool could not complete the same-named assembly pre-check (see the log), so the merge package was NOT merged into the Toolkit (nothing was written).\n\nNote: this is NOT a detected conflict - the pre-check itself could not decide. It guards against a later mod silently replacing an assembly already in the Toolkit, which leaves the earlier mod's part scripts as missing script. When it cannot decide, it stops and reports rather than gambling.\n\nPlease retry; if it keeps failing, report it along with the error line in the log.\n\nThe merge package is still at: {path}",
        "install_asm_conflict_body": "The Toolkit already has a same-named assembly with **different content**, so the merge package was NOT merged in (nothing was written).\n\n{list}\n\nAn assembly filename cannot be renamed: Unity's MonoScript stores it in m_AssemblyName, and Unity cannot resolve the classes inside once it changes. When two mods' dlls share a name only the first one survives - importing the second leaves the first mod's part scripts as missing script.\n\nWhat to do:\n- A Toolkit currently holds one mod assembly. To use two mods with custom scripts at once, merge the two dlls by hand (rename the classes in the second dll, otherwise Unity reports CS0101 duplicate type definition), then import with this tool.\n- Using only one: delete the earlier mod's part prefabs and its dll + .meta under Assets/Plugins, then import this mod.\n- If both dlls really come from the same mod, the file was modified - review it by hand before importing.\n\nThe merge package is still at: {path}",
        "packdata_done": "[PackData] Generated PackData asset {path} and labeled {labeled} assets '{label}'. In Unity: SFS -> Build Pack, pick the asset + label to build.",
        "packdata_fail": "[PackData] [!] Auto-generation failed: {error} (create it manually in Unity)",
        "packdata_skipped_refused": "[PackData] Merge was refused; no PackData asset generated (nothing of this mod is in the Toolkit yet, so it would be an empty build entry).",
        "log_dedupe_fail": "[Dedupe] [!] In-project dedupe failed: {exc}",
        "repair_start": "Cleaning leftover AssetRipper stub shaders in the Toolkit (the cause of black parts)...",
        "repair_done": "[Repair] Deleted {stubs} stub shaders, rewrote {refs} material refs, synced {names} asset names. Backup at {backup}",
        "repair_none": "[Repair] No stub shaders found; the Toolkit is clean.",
        "repair_dangling_none": "[Dangling] No dangling references found; the Toolkit is clean.",
        "repair_dangling_scan": "[Dangling] Scanned {n} dangling references",
        "repair_dangling_redirected": "[Dangling] Redirected {n} references by name",
        "repair_dangling_imported": "[Dangling] Imported {m} missing assets into the Toolkit: {names}",
        "repair_dangling_unresolved": "[Dangling] {n} references could not be auto-fixed; manifest at {path}",
        "repair_dangling_nopkg": "[Dangling] No original mod project dir provided; scan+manifest only. To auto-fix, fill the original mod project dir.",
        "repair_dangling_clean": "[Repair] Dangling refs: redirected {redirected}, imported {imported}, unresolved {unresolved}",
        "select_package": "Select",
        "install_failed": "[Install] Failed to write into the Toolkit: {error}",
        "selected_pack": "Source selected: {name}",
        "selected_translation": "Translation selected: {name}",
        "toolkit_dir": "Modding Toolkit project path:",
        "select_toolkit": "Select Toolkit",
        "toolkit_hint": "Required. Parts are exported and merged straight into this Modding Toolkit (only parts it does not already have are added). Staging is temporary; new parts are written into the Toolkit's Assets.",
        "selected_toolkit": "Toolkit selected: {path}",
        "installed_to_toolkit": "Done: {new} new parts merged into the Toolkit ({skip} already-present parts skipped, {copy} assets copied). Open Assets/Resources/Parts/{sub} in the Toolkit to see and edit them.",
        "need_toolkit": "Modding Toolkit path required",
        "need_toolkit_text": "You must choose a valid Modding Toolkit project path before exporting.\nReason: the exported part prefabs reference game scripts that come from the Toolkit; without it the parts will be broken/uneditable.\nSelect the Toolkit project root that contains Assets\\Scripts.",
        "need_toolkit_invalid": "Invalid Modding Toolkit path",
        "toolkit_root_fixed": "[TK] The chosen folder was not the Toolkit project root; using {path}",
        "need_toolkit_invalid_text": "The chosen folder is not a valid Toolkit project: no .cs.meta scripts found under Assets\\Scripts.\nSelect the official Modding Toolkit project root (containing Assets\\Scripts\\Assembly-CSharp, etc.).",
        "extract_start": "Extracting text...",
        "no_pack_log": "❌ No mod.pack selected",
        "json_error": "❌ JSON read error: {error}",
        "scan": "  Scanning {build}...",
        "unpack_error": "  ❌ {build} unpack failed: {error}",
        "extract_done": "✔ Extraction completed: {count} strings → {path}",
        "no_translation": "❌ No translation JSON selected",
        "read_failed": "❌ File read failed: {error}",
        "writing": "Writing {build}...",
        "decode_failed": "  ❌ {build} decode failed: {error}",
        "write_done": "  ✔ {build} done, {count} changes",
        "save_failed": "  ❌ {build} save failed: {error}",
        "pack_done": "✔ Output created: {path}",
        "output_failed": "❌ Output failed: {error}",
        "processing_failed": "❌ Processing failed: {error}",
        "strip_frame": "Strip / Slim Tool",
        "strip_hint": "Strip = keep only the checked platform Builds and CodeAssembly, remove other platforms to greatly reduce .pack size.\nThe pack is scanned first to guarantee at least one platform remains.",
        "target_platform": "Platforms to keep (multi-select):",
        "select_strip_output": "Output location:",
        "pick_strip_output": "Browse...",
        "analyze": "Pack info",
        "strip": "Strip Selected",
        "strip_scan_header": "[Strip] Pack scanned: {builds} platform(s): {list}",
        "strip_scan_plat": "    {plat}: {size}",
        "strip_missing_warn": "[Strip] [!] Selected platforms {missing} are not in the pack; keeping {kept} only.",
        "strip_no_target": "❌ None of the selected platforms ({wanted}) are in this .pack. Pack contains: {present}. Run Pack info first.",
        "strip_none_selected": "❌ Check at least one platform to keep.",
        "analyzing": "Analyzing pack info...",
        "pack_size": "  Pack file: {content} ({size})",
        "assembly": "    CodeAssembly: {size}",
        "assembly_absent": "    CodeAssembly: not included",
        "build_present": "    {plat}: ~{size} decompressed, {parts} parts",
        "build_absent": "   {plat}: not included",
        "analyze_done": "✔ Pack info done: {builds} platforms, {parts} parts, ~{total} decompressed",
        "strip_output_is_input": "❌ Strip output cannot be the source .pack (it would overwrite the original mod). Pick another path.",
        "strip_output_set": "Strip output: {path}",
        "strip_no_pack": "❌ No mod.pack selected",
        "strip_no_output": "❌ No output location set, created in the source folder",
        "strip_start": "Stripping...",
        "strip_read_fail": "❌ Failed to read .pack: {error}",
        "strip_removed": "  Removed {plat}",
        "strip_keep": "  Kept {plat}",
        "strip_done": "✔ Strip done: {out} ({size})",
        "strip_fail": "❌ Strip failed: {error}",
        "tutorial_missing": "tutorial.html not found; make sure it sits next to this program",
        "menu_tutorial": "Tutorial",
        "menu_tutorial_open": "Usage tutorial (HTML)",
        "menu_author": "About Author",
        "menu_author_open": "Author & QQ group",
        "menu_about": "About App",
        "menu_about_open": "How it works",
        "about_app_title": "About SFS Pack Tool",
        "about_author_title": "About the Author",
        "about_close": "Close",
        "link_qq": "Join QQ group 【𝔸𝔽𝕊 ℍ𝕦𝕓】",
        "qq_hint": "QQ group: 923038827",
        "log_align_done": "[NoHang] Done: rewrote {rewritten} prefab/asset, {refs} script refs",
        "log_align_skip": "[NoHang] Not run: {error}",
        "log_align_fail": "[NoHang] Alignment failed; exported project unaffected: {exc}",
        "log_scan_fail": "Pack scan failed: {exc}",
        "scan_unreliable_title": "Custom class detection is unreliable",
        "scan_unreliable_log": "[Scan] [!] Custom class detection is unreliable ({reason}); fell back to the '{source}' heuristic, so later auto-fixes may be incomplete",
        "scan_unreliable_body": "This mod's custom script classes could **not** be determined reliably, so this export fell back to the conservative '{source}' heuristic.\n\nReason: {reason}\n\nWhy you must know: this heuristic also counts stock classes that are not found in the Toolkit as mod custom classes. The tool itself stays conservative (it will not delete anything on an undecided call), but the \"N custom classes\" figure you see is not trustworthy and later auto-fixes may be incomplete.\n\nThis usually means the Toolkit version differs from the mod author's, or the pack has an unusual structure. You can still export; if scripts end up missing, suspect this first instead of re-exporting repeatedly.",
        "scan_ilspy_title": "No ILSpy - custom script sources are not shown",
        "scan_ilspy_body": "This mod carries custom scripts, but the decompiler ilspycmd was not found, so automatic decompilation was skipped.\n\nThis does **not** affect importing or building (the custom scripts still come from the mod's own dll) - you just cannot read the sources.\n\nTo view/modify these custom scripts, pick either:\n- Install the ILSpy command line: dotnet tool install -g ilspycmd (then reopen this tool)\n- Or decompile the dll under Assets/Plugins by hand with dnSpy",
        "log_organize_skip": "Mod asset grouping skipped: {error}",
        "log_organize_fail": "Mod asset grouping failed: {exc}",
        "log_shader_fail_export": "[Shader] Handling failed; exported project unaffected: {exc}",
        "log_merge_done": "[Merge] Pure-new merge package {pkg}: new parts {new}, skipped existing {skip}, copied assets {copy}",
        "log_merge_none": "[Merge] Not generated: {error}",
        "log_merge_fail": "[Merge] Generation failed; exported project unaffected: {exc}",
        "log_verify_hit": "[Verify] Exported project script refs: hit {hit}/{total}, missing {miss}",
        "log_verify_missing": "[Verify] [!] {n} prefabs have missing script refs: {files}",
        "log_verify_fail": "[Verify] Self-check of script refs failed; export result unaffected: {exc}",
        "log_gate_blocked": "[GATE] [!!] {n} script GUIDs still have no matching script; {refs} refs would hang",
        "log_gate_stop": "[GATE] [!!] Refused to merge into Toolkit so hanging prefabs are not injected. See {path}",
        "log_gate_classes": "[GATE] [!!] Classes not wired up: {classes}",
        "log_gate_title": "Scripts not wired up - merge refused",
        "log_gate_body": "{n} script refs in the exported project are still unresolved ({refs} occurrences).\n\nClasses not wired up:\n{classes}\n\nMerging them would flood Unity with 'Script is missing'.\nThe tool stopped the merge and wrote a checklist to:\n{path}\n\nMost common cause: the Toolkit version differs from the one the mod author used.",
        "about_app_text": "SFS Pack Tool is an all-in-one mod tool covering:\n• Localization: extract/write translatable text from mod.pack\n• Prefab export: decompile .pack into a Unity project via the bundled AssetRipper\n• No-hang alignment: auto-swap AssetRipper placeholder scripts for real Toolkit sources\n• Stub shader fix: replace black-board-causing placeholder shaders with real ones\n• Dangling-ref self-heal: fix or import missing assets by name/GUID\n• Merge package: trim only the new content Toolkit lacks, then merge safely\n\nHow it works: export stages in a temp dir, prefers copy-mode to swap in real shader sources (keeping GUIDs), rewrites script GUID maps by class name, then pre-checks GUID collisions.",
        "about_author_text": "Author: A Future star\nThis tool is developed and maintained by A Future star to lower the SFS modding barrier.\nFor questions or suggestions, join the QQ group.",
    },
}


def _zh2en(msg: str) -> str:
    """把 keepalive 内部日志里的中文(主要前缀标签与少量短语)翻成英文。

    轻量替换：先翻 [标签]，再翻少量多词短语；数字/文件名/列表原样保留，
    因此英文模式下日志以英文呈现，且不会丢失关键信息。
    """
    if not msg:
        return msg
    tags = {
        "[免挂]": "[NoHang]",
        "[着色器]": "[Shader]",
        "[合并]": "[Merge]",
        "[悬空]": "[Dangling]",
        "[对齐]": "[Align]",
        "[自定义]": "[Custom]",
        "[命名]": "[Name]",
        "[修复]": "[Repair]",
        "[安装]": "[Install]",
        "[校验]": "[Verify]",
        "[扫描]": "[Scan]",
        "[整理]": "[Group]",
        "[闸门]": "[GATE]",
        "[去重]": "[Dedupe]",
        "[PackData]": "[PackData]",
    }
    phrases = [
        # --- PackData / 去重 / 单平台解码（整句优先 防止被后面的通用短语缝合成怪句）---
        ("[PackData] 生成 PackData 资产", "[PackData] generated PackData asset"),
        ("[PackData] 更新 PackData 资产", "[PackData] updated PackData asset"),
        ("PackData 资产", "PackData asset"),
        ("(显示名", "(display name"),
        ("[PackData] 未找到 PackData.cs 跳过生成（目录不是 Modding Toolkit 工程？）",
         "[PackData] PackData.cs not found; skipped (not a Modding Toolkit project?)"),
        ("[PackData] 原包里没读到 PackData 元数据 跳过生成（可在 Unity 手动建）",
         "[PackData] no PackData metadata in the original .pack; skipped (create it manually in Unity)"),
        ("[PackData] 已给", "[PackData] labeled"),
        ("资产的 .meta 设置 AssetBundle 标签", " assets' .meta with AssetBundle label"),
        ("(改动已备份到", "(changes backed up to"),
        ("(已禁用)", "(disabled)"),
        ("原包带自定义脚本 已导出", "pack carries custom scripts; exported"),
        ("(构建弹窗时选择它)", "(pick it in the build dialog)"),
        ("已导出原包图标并挂到 PackData", "original pack icon exported and wired to PackData"),
        ("[Dedupe] 重复资产", "[Dedupe] duplicate assets removed:"),
        ("个已移除 引用重写", ", rewrote"),
        ("处 (组", " refs ("),
        ("[Dedupe] 发现", "[Dedupe] found"),
        ("个同名不同内容的资产 原样保留", " same-named assets with different content; kept as-is"),
        ("个同名不同内容的资产已保留 (真变体)", " same-named assets with different content; kept (true variants)"),
        ("单平台导出：仅解码", "single-platform export: decoding only"),
        ("（其余", " (the other"),
        ("平台内容相同 跳过避免重复）", " platform(s) carry identical content; skipped to avoid duplicates)"),
        ("字节 已导出", "bytes, exported"),
        ("已解码", "decoded"),
        ("字节", "bytes"),
        ("[!] 跳过", "[!] skip:"),
        ("按资产名对齐", "aligned by asset name:"),
        ("的脚本类", " script classes"),
        ("以下原版类在 Toolkit 中找不到源码 无法接上", "these stock classes have no source in the Toolkit; cannot wire:"),
        ("（已有 stub 可用 忽略）", "(a stub is available; ignored)"),
        ("反编译没有产出", "decompile produced nothing:"),
        ("反编译调用失败", "decompile call failed:"),
        ("未找到 ilspycmd 跳过自动反编译", "ilspycmd not found; auto-decompile skipped"),
        ("未找到 ilspycmd 已跳过自动反编译 不影响导入与出包 只是看不到源码。",
         "ilspycmd not found; auto-decompile skipped. Importing/building are unaffected, you just cannot see the sources."),
        ("如需查看/修改模组自定义脚本 请安装 ILSpy 命令行工具",
         "To view/modify the mod's custom scripts, install the ILSpy command line tool"),
        ("dotnet tool install -g ilspycmd 或用 dnSpy 手动反编译",
         "(dotnet tool install -g ilspycmd), or decompile manually with dnSpy"),
        ("自定义类判定不可靠（", "custom class detection is unreliable ("),
        ("）已退化为", "); fell back to "),
        ("包内类名 − Toolkit 类名", "pack classes minus Toolkit classes"),
        ("口径 后续自动修复可能不完整", " heuristic, so later auto-fixes may be incomplete"),
        ("读到了", "read"),
        ("个 MonoScript 类名 但都没有 m_AssemblyName 字段",
         " MonoScript class names but none carries m_AssemblyName"),
        ("（UnityPy 未能解析该字段）无法区分自定义类与原版类",
         " (UnityPy could not read that field); custom classes cannot be told apart from stock ones"),
        ("未能读出 MonoScript 的程序集信息（", "could not read MonoScript assembly info ("),
        ("）", ")"),
        ("已跳过自动反编译", "auto-decompile skipped"),
        ("kept不动", "kept untouched"),
        ("Toolkit 已有部件", "Toolkit existing parts:"),
        ("Toolkit 里已有但脚本挂空 本次一并更新", "already in Toolkit with hanging scripts; updated too"),
        ("Toolkit 自带部件", "Toolkit bundled parts"),
        ("Toolkit 缺少 Assets 目录", "Toolkit lacks an Assets directory"),
        ("Toolkit 脚本已拷贝 但未能读出任何 .cs.meta GUID", "Toolkit scripts copied but no .cs.meta GUID readable"),
        ("已与 prefab 引用一一对应 贴进 Toolkit 后无需重新挂接", "one-to-one with prefab refs; no re-mounting needed in the Toolkit"),
        ("重写 materials引用", "rewrote materials refs at"),
        ("deletedstub", "deleted stub"),
        ("materials现指向 Toolkit 真着色器", "materials now point to real Toolkit shaders"),
        ("CodeAssembly 有", "CodeAssembly:"),
        ("CodeAssembly 无", "CodeAssembly: none"),
        ("Plugins 里还没有同名", "no same-named dll yet in Plugins:"),
        (".pack 根节点必须是 JSON 对象", ".pack root must be a JSON object"),
        ("AssetRipper 完成后未找到任何 .prefab 文件", "no .prefab files found after AssetRipper finished"),
        ("AssetRipper 启动后立即退出 退出码", "AssetRipper exited immediately, code"),
        ("AssetRipper 已下载 但未找到", "AssetRipper downloaded but missing:"),
        ("未找到 AssetRipper 正在下载", "AssetRipper not found; downloading"),
        ("AssetRipper 请求", "AssetRipper request"),
        ("未在 .pack 中找到可用 UnityFS AssetBundle 检查字段", "no usable UnityFS AssetBundle fields found in the .pack:"),
        ("❌ 已取消", "❌ cancelled"),
        ("音频以 byte[] 内嵌在 .asset 里 不会自动变成可播放的 .wav/.ogg 提取后才可试听",
         "audio is embedded as byte[] inside .asset; export it first to get a playable .wav/.ogg"),
        ("materials 现指向 Toolkit 真着色器", "materials now point to real Toolkit shaders"),
        ("重写 materials 引用", "rewrote materials refs at"),
        ("AssetRipper 完成后未生成 Assets 目录", "Assets directory not generated after AssetRipper"),
        ("可执行文件", "executable"),
        ("日志已复制到", "log copied to"),
        ("真 dll 当插件", "real dll as plugin"),
        ("程序集", "assembly"),
        ("类名", "class name"),
        ("<冲突>", "<collision>"),
        ("发现", "found"),
        ("版本", "version"),
        ("作者", "author"),
        ("空壳", "stub"),
        ("说明这份 Toolkit 混入了 AssetRipper 占位 stub", "this Toolkit contains AssetRipper placeholder stubs"),
        ("会自动跳过这些 stub 但建议换成干净的 Toolkit 工程", "these stubs are auto-skipped; recommend a clean Toolkit project"),
        ("这份 Toolkit 被 AssetRipper 处理过 建议清理后重试", "this Toolkit was processed by AssetRipper; clean it then retry"),
        ("这份 Toolkit 自带的部件就有", "this Toolkit's own bundled parts have"),
        ("通常是 Toolkit 版本与 mod 作者用的不一致", "usually the Toolkit version differs from the mod author's"),
        ("或 .meta 被重新生成过", "or the .meta was regenerated"),
        ("这种情况下免挂不会生效", "in this case NoHang won't take effect"),
        ("请换成与 mod 作者相同的 Toolkit 版本", "use the same Toolkit version as the mod author"),
        ("以下类在 Toolkit 中无源码 无法保证解析(可能来自 mod 的 CodeAssembly)", "these classes have no source in the Toolkit; parsing not guaranteed (may come from the mod's CodeAssembly)"),
        ("个文件仍存在未解析脚本引用", " files still have unresolved script references"),
        ("Toolkit 脚本数", "Toolkit script count:"),
        ("Toolkit 自身有", "Toolkit itself has"),
        ("个重复类型定义", " duplicate type definitions"),
        ("Toolkit 自检 自带部件", "Toolkit self-check: bundled parts"),
        ("脚本引用命中", "script refs hit"),
        ("处脚本对不上", " script refs unmatched"),
        ("包内脚本类数(并集)", "pack script classes (union):"),
        ("该 pack 未携带 CodeAssembly", "this pack has no CodeAssembly"),
        ("个自定义脚本 拿不到源码 只能保留空壳 stub", " custom scripts: no source, kept as stubs"),
        ("个将被替换的 AssetRipper stub 脚本", " AssetRipper stub scripts to be replaced"),
        ("未找到 Toolkit 脚本目录 跳过导入", "Toolkit script dir not found; import skipped"),
        ("个 Toolkit 脚本(含 .meta)", " Toolkit scripts (with .meta)"),
        ("个 Toolkit 自带的 AssetRipper stub", " AssetRipper stubs bundled in Toolkit"),
        ("已建立脚本 GUID 重写映射", "Built script GUID rewrite map:"),
        ("个 prefab/asset 共", " prefabs/assets, total"),
        ("处脚本引用", " script references"),
        ("已重写", "Rewrote"),
        ("已删除", "Deleted"),
        ("已整拷", "Copied"),
        ("已跳过", "Skipped"),
        ("已换成 Toolkit 真着色器", "replaced with real Toolkit shaders"),
        ("Toolkit 里找不到同名真着色器", "no same-named real shader found in Toolkit"),
        ("空壳着色器处理失败", "stub shader handling failed"),
        ("合并包着色器重指向失败", "merge-package shader redirect failed"),
        ("同名资源对齐失败", "same-name asset alignment failed"),
        ("GUID 冲突", "GUID collision"),
        ("处 拷入后可能与 Toolkit 既有资产撞 GUID", " locations; may collide with existing Toolkit assets"),
        ("新增部件", "new parts:"),
        ("Toolkit 已有而跳过", "already in Toolkit, skipped:"),
        ("个新增部件文件名重复 只保留第一个", " new parts have duplicate filenames; kept only the first"),
        ("已带上 mod 程序集", "bundled mod assembly"),
        ("个(DLL) 自定义脚本引用据此解析", " (DLL); custom script refs resolved accordingly"),
        ("已带上 ModCode 自定义脚本", "bundled ModCode custom scripts:"),
        ("自定义脚本引用据此解析", "custom script refs resolved accordingly"),
        ("类型重复定义", "duplicate type definition"),
        ("保留", "kept"),
        ("删除", "deleted"),
        ("个资产的 m_Name 对齐到文件名", " assets had m_Name aligned to filename"),
        ("检出 CodeAssembly", "found CodeAssembly"),
        ("字节 已导出", "bytes, exported"),
        ("已把 DLL 放在", "DLL placed at"),
        ("可用 ILSpy 或 dnSpy 手动反编译", "use ILSpy or dnSpy to decompile manually"),
        ("保留 mod 自有程序集", "kept mod's own assembly"),
        ("prefab 的自定义脚本引用已指向该 DLL → 导出工程可直接解析，无需挂接", "prefab custom script refs now point to this DLL -> project parses directly, no mounting needed"),
        ("反编译源码另存为工程外", "decompiled sources saved outside the project"),
        ("文件) 供阅读 / 改后重编译", "files) for reading / recompiling after edits"),
        ("已从 DLL 还原", "restored from DLL"),
        ("个自定义脚本文件 → Assets/Scripts/", " custom script files -> Assets/Scripts/"),
        ("其中", "of which"),
        ("个是 prefab 引用的类", "are classes referenced by prefabs"),
        ("扫描到", "Scanned"),
        ("处悬空引用", "dangling references"),
        ("已按同名重定向", "redirected by name:"),
        ("已补入 Toolkit 缺失资产", "imported missing Toolkit assets:"),
        ("无法自动修复", "could not be auto-fixed:"),
        ("处 清单见", " locations; manifest at"),
        ("未提供原始 mod 工程目录 仅完成扫描+清单 如需自动修复请填写原始 mod 工程目录", "original mod project dir not provided; scan+manifest only. Provide it to auto-fix."),
        ("与 Toolkit 同名资源", "same-name assets as Toolkit:"),
        ("个 全部保留了 mod 版本", " all kept the mod version"),
        ("与 Toolkit 同名的原版资源", "original assets same-named as Toolkit:"),
        ("个 已改指 Toolkit 那份(重写引用", " redirected to the Toolkit copy (rewrote refs"),
        ("处 移除副本", " locations, removed copies"),
        ("个同名资源内容与 Toolkit 不同 已保留 mod 版本并改名", " same-named assets differ from Toolkit, kept mod version and renamed"),
        ("未发现悬空引用 Toolkit 已是干净的", "no dangling references found; Toolkit is clean"),
        ("纯新增合并包", "pure-new merge package"),
        ("跳过已有", "skipped existing"),
        ("拷贝资产", "copied assets"),
        ("完成 重写", "done: rewrote"),
        ("未执行", "not run:"),
        ("对齐失败 不影响已导出的工程", "alignment failed; exported project unaffected:"),
        ("处理失败 不影响已导出的工程", "handling failed; exported project unaffected:"),
        ("未生成", "not generated:"),
        ("生成失败 不影响已导出的工程", "generation failed; exported project unaffected:"),
        ("导出工程脚本引用 命中", "exported project script refs hit"),
        ("缺失", "missing"),
        ("个 prefab 存在缺失脚本引用", "prefabs have missing script refs"),
        ("自检脚本引用失败 不影响导出结果", "self-check of script refs failed; export result unaffected:"),
        # --- 解包前扫描 / 方案B / Pack Data / 资产归拢 ---
        ("建议路线", "suggested route:"),
        ("缺少平台包", "missing platform bundle(s):"),
        ("（该平台将无法构建，通常不影响 Windows/Android）", " (that platform cannot be built; usually fine for Windows/Android)"),
        ("CodeAssembly 不是有效 PE(dll) 文件", "CodeAssembly is not a valid PE (dll) file"),
        ("未能解析 MonoScript 类名", "could not parse MonoScript class names:"),
        ("含自定义类但包内没有 CodeAssembly 自定义脚本无法自动提供 需人工处理", "has custom classes but no CodeAssembly; custom scripts cannot be provided automatically, handle manually"),
        ("dll 未引用 Assembly-CSharp 可能不依赖 SFS 游戏类型 请核对与 Toolkit 版本是否一致", "dll does not reference Assembly-CSharp; it may not depend on SFS game types, verify against the Toolkit version"),
        ("自定义类", "custom classes:"),
        ("dll 依赖", "dll references:"),
        ("CodeAssembly 有", "CodeAssembly present,"),
        ("CodeAssembly 无", "CodeAssembly none"),
        ("字节", "bytes"),
        ("方案B 已落位插件", "Plan B: plugin installed"),
        ("→ 自定义类由 dll 提供 无需改写 prefab", "-> custom classes come from the dll, no prefab rewrite needed"),
        ("个与 dll 撞类的 stub（防 CS0101）", " stub(s) clashing with the dll (prevents CS0101)"),
        ("改走源码路线 已撤回落位的 dll", "switching to the source route; withdrew the installed dll"),
        ("模组资产已归拢到", "mod assets grouped under"),
        (".asset 已保留", ".asset files preserved:"),
        ("其中含音频字节流的 Pack Data", "of which Pack Data containing audio bytes:"),
        (".asset 数量不一致 源", ".asset count mismatch: source"),
        ("请检查磁盘空间或权限", "check disk space or permissions"),
        # --- 导出器（AssetRipper 流程）日志 ---
        ("已解码", "Decoded"),
        ("该字段不是 Base64 字符串", "field is not a Base64 string"),
        ("Base64 解码失败", "Base64 decode failed"),
        ("解码内容不是 UnityFS AssetBundle", "decoded content is not a UnityFS AssetBundle"),
        ("CodeAssembly 解码失败 继续只导出资源", "CodeAssembly decode failed; continuing with assets only"),
        ("使用 AssetRipper", "Using AssetRipper"),
        ("为保护已有文件 工程将导出到新目录", "to protect existing files, the project will be exported to a new directory"),
        ("为保护已有文件 ZIP 将保存为", "to protect existing files, the ZIP will be saved as"),
        ("正在启动 AssetRipper", "Starting AssetRipper"),
        ("检测到旧版 AssetRipper 正在使用兼容参数重启", "older AssetRipper detected; restarting with compatible args"),
        ("检测到已知 Windows 崩溃码", "known Windows crash code detected:"),
        ("改用兼容参数重启 复用内置版本 不联网下载", "restarting with compatible args, reusing the bundled build, no download"),
        ("正在加载解码后的 AssetBundle", "Loading the decoded AssetBundle"),
        ("正在导出 Unity 工程与 Prefab 资源较多时请耐心等待", "Exporting the Unity project and prefabs; this can take a while"),
        ("个 Prefab YAML", " prefabs (YAML:"),
        ("贴图", " textures"),
        ("材质", " materials"),
        ("平台", "platforms"),
        ("已移除", "Removed"),
        ("已导出", "Exported"),
        ("ProjectSettings=", " ProjectSettings="),
        ("个 Prefab YAML", " prefabs, YAML:"),
        (" 个 ", " "),
        ("个", ""),
        ("工程文件 Packages", "project files: Packages"),
        ("已生成 ZIP", "ZIP created:"),
        ("完成 Unity 工程目录", "Unity project directory ready:"),
        ("=有", "=yes"),
        ("=无", "=no"),
        ("=是", "=yes"),
        ("=否", "=no"),
        # --- .pack 权威脚本映射 / 合并闸门 ---
        ("[闸门]", "[GATE]"),
        ("已从 .pack 读出", "read from .pack:"),
        ("个 prefab 的脚本布局", " prefabs' script layout"),
        ("(共", "(total"),
        ("处引用)", " refs)"),
        ("结构对齐", "structural alignment:"),
        ("个 prefab 还原出", " prefabs resolved"),
        ("个脚本 GUID 的真实类名", " script GUIDs to real class names"),
        ("个 prefab 未能与 .pack 对齐", " prefabs could not be aligned with .pack"),
        ("AssetRipper 未生成任何脚本 stub", "AssetRipper generated no script stubs"),
        ("已改用 .pack 结构对齐还原", "fell back to .pack structural alignment, resolved"),
        ("未能从 .pack 读取脚本布局", "could not read script layout from .pack:"),
        ("在 stub 里是", "is"),
        ("在 .pack 里是", "in .pack but"),
        ("以 .pack 为准", "in stub; .pack wins"),
        ("已把", "Pointed"),
        ("个自定义脚本 GUID 指到插件 DLL", " custom script GUIDs at the plugin DLL"),
        ("重写后仍有", "after rewriting, still"),
        ("个脚本 GUID 在工程里找不到", " script GUIDs missing from the project"),
        ("共", "total"),
        ("处引用会挂空", " refs would hang"),
        # --- 通用兜底（列表按长度降序自动排序 短词天然最后替换）---
        ("失败", "failed"),
        ("目录", "directory"),
        ("跳过", "skip"),
        (" 处", " locations"),
        ("目标", "target"),
        ("检查磁盘空间或权限", "check disk space or permissions"),
        ("个)", " groups)"),
    ]
    out = msg
    for zh, en in tags.items():
        out = out.replace(zh, en)
    for zh, en in sorted(phrases, key=lambda kv: len(kv[0]), reverse=True):
        if zh in out:
            out = out.replace(zh, en)
    return out


def format_asm_conflicts(conflicts: list[dict], limit: int = 6) -> str:
    """把同名程序集冲突清单排成弹窗用的多行文本（逐条点名是哪两个模组）。

    模组名反查不到时显示 "?"——宁可留个空让人问，也不要编一个模组名。
    独立成函数：弹窗正文要能离线断言（见 test_core_smoke 的 P0-1 用例）。
    """
    lines: list[str] = []
    for c in conflicts[:limit]:
        old = c.get("existing_owner") or "?"
        new = c.get("incoming_owner") or "?"
        old_g = (c.get("existing_guid") or "?")[:8]
        new_g = (c.get("incoming_guid") or "?")[:8]
        lines.append(
            f"• {c.get('name', '?')}（{c.get('rel', '?')}）\n"
            f"    Toolkit 现有：{old} 的程序集（guid {old_g}）\n"
            f"    本次要装：{new} 的程序集（guid {new_g}）"
        )
    if len(conflicts) > limit:
        lines.append("...")
    return "\n".join(lines)


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


APP_USER_MODEL_ID = "AFuturestar.SFSPackTool.2.3.6-PyQt"
_WM_SETICON = 0x0080
_IMAGE_ICON = 1
_LR_LOADFROMFILE = 0x00000010


def app_data_dir() -> Path:
    root = Path(os.environ.get("APPDATA", Path.home())) if os.name == "nt" else Path.home() / ".config"
    folder = root / "AFuturestar" / "SFS-Pack-Tool"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def resolve_toolkit_root(path) -> Path | None:
    """把所选目录解析成 Toolkit 工程根。

    用户很容易点进 Assets/Scripts/Parts/Mesh 这类子目录，这里向上找出第一个
    真正含 Assets/Scripts 的目录；优先返回 Scripts 顶层就有 .cs.meta 的那个。
    都找不到返回 None。
    """
    current = Path(path).resolve()
    loose: Path | None = None
    for cand in [current, *current.parents]:
        scripts = cand / "Assets" / "Scripts"
        if not scripts.is_dir():
            continue
        if next(scripts.glob("*.cs.meta"), None) is not None:
            return cand
        if loose is None:
            loose = cand
    return loose


SETTINGS_PATH = app_data_dir() / "settings.json"
# 日志目录：与设置同根，用户可以把整个目录打包发给作者
LOG_DIR = app_data_dir() / "logs"


def load_settings() -> dict:
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(data: dict) -> None:
    try:
        SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def leaf_field(path: str) -> str:
    """取路径最末尾的字段名；列表元素去掉下标。"""
    return path.split(".")[-1].split("[")[0]


def is_exclude_word(text: object) -> bool:
    return isinstance(text, str) and text.strip() in EXCLUDE_WORDS


LOC_KEY_SUFFIXES = ("Name", "Description", "Text", "Title", "Label", "DisplayName", "Key", "Unit", "Units", "Author")
_LOC_SUFFIX_RE = re.compile(r"_(" + "|".join(LOC_KEY_SUFFIXES) + r")$")


def is_loc_key(text: object) -> bool:
    """是否形似本地化 key（如 "0_0_Description"）：纯 ASCII 标识符 + _字段名 结尾。"""
    if not isinstance(text, str):
        return False
    if not re.fullmatch(r"[A-Za-z0-9_]+", text):
        return False
    return bool(_LOC_SUFFIX_RE.search(text))


def is_meaningful_text(text: object) -> bool:
    """过滤太短/纯数字/程序符号/内部 key 的串。"""
    if not isinstance(text, str) or len(text) < 2:
        return False
    if re.match(r"^[0-9\s\.\,\%\+\-\*\/\(\)]+$", text):
        return False
    if is_loc_key(text):
        return False
    for token in ("UnityEngine", "Assembly-", "SFS.", "System.", "None"):
        if token in text:
            return False
    return True


def is_display_text(text: object, path: str) -> bool:
    """标准扫描：仅取“显示字段”叶节点的值，天然不碰内部变量名。"""
    if not is_meaningful_text(text) or is_exclude_word(text):
        return False
    return leaf_field(path) in DISPLAY_LEAF_FIELDS


def is_candidate_text(text: object, path: str) -> bool:
    """深度扫描：非显示、非明确内部字段的串，进人工确认区，绝不自动写回。"""
    leaf = leaf_field(path)
    if not is_meaningful_text(text) or is_exclude_word(text):
        return False
    return leaf not in DISPLAY_LEAF_FIELDS and leaf not in INTERNAL_LEAF_FIELDS


def is_plain_text(parent: object) -> bool:
    """TranslationVariable 结构里 plainText 是否为真。

    游戏源码 SFS.Translations.TranslationVariable：plainText=0 时
    TranslatableName 是按 key 查 Loc.fields 的翻译标识符（查不到会显示 NULL），
    只有 plainText=1 时才是直显文本、可安全汉化。parent 里没有 plainText
    字段时按 C# 默认值 false 处理（即视为 key，宁可不翻，不可翻坏）。
    """
    if not isinstance(parent, dict):
        return False
    return bool(parent.get("plainText"))


def recursive_walk(node: object, path: str, callback) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}" if path else str(key)
            if isinstance(value, str):
                callback(node, key, value, child)
            elif isinstance(value, (dict, list)):
                recursive_walk(value, child, callback)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            child = f"{path}[{index}]"
            if isinstance(value, str):
                callback(node, index, value, child)
            elif isinstance(value, (dict, list)):
                recursive_walk(value, child, callback)


def extract_texts(input_file: str, output_file: str, translate, log) -> None:
    if not input_file:
        log(translate("no_pack_log"))
        return
    log(translate("extract_start"))
    try:
        data = json.loads(Path(input_file).read_text(encoding="utf-8-sig"))
    except Exception as exc:
        log(translate("json_error", error=exc))
        return
    texts: set[str] = set()
    candidates: set[str] = set()
    for build in PLATFORM_KEYS:
        if not data.get(build):
            continue
        log(translate("scan", build=build))
        try:
            environment = UnityPy.load(base64.b64decode(data[build]))
        except Exception as exc:
            log(translate("unpack_error", build=build, error=exc))
            continue
        for obj in environment.objects:
            try:
                if obj.type.name == "MonoBehaviour":
                    tree = obj.read_typetree()
                    if tree is not None:

                        def collect(parent, key, value, path) -> None:
                            # 翻译 key 过滤：TranslatableName 且 plainText=0 的是游戏查表用的 key
                            if key == "TranslatableName" and not is_plain_text(parent):
                                return
                            # 官方翻译 key 过滤：与 SFS_Translation.cs 里的 key 撞名的串绝不能汉化
                            if value in OFFICIAL_LOC_KEYS:
                                return
                            if is_display_text(value, path):
                                texts.add(value)
                            elif is_candidate_text(value, path):
                                candidates.add(value)

                        recursive_walk(tree, "", collect)
            except Exception:
                continue
    table = {item: item for item in sorted(texts)}
    if candidates:
        table[CANDIDATES_KEY] = {item: item for item in sorted(candidates)}
    output = Path(output_file) if output_file else Path(input_file).with_name("texts_to_translate.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(table, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(translate("extract_done", count=len(texts), path=output))


def write_translation(input_file: str, translation_file: str, author: str, translate, log) -> None:
    if not input_file:
        log(translate("no_pack_log"))
        return
    if not translation_file:
        log(translate("no_translation"))
        return
    try:
        data = json.loads(Path(input_file).read_text(encoding="utf-8-sig"))
        translations = json.loads(Path(translation_file).read_text(encoding="utf-8-sig"))
    except Exception as exc:
        log(translate("read_failed", error=exc))
        return
    # 跳过“人工确认区”：不在标准翻译表里的疑似变量即使写了也绝不写回 Pack。
    translations = {
        source: target
        for source, target in translations.items()
        if isinstance(source, str) and source != target and source != CANDIDATES_KEY
    }
    for build in PLATFORM_KEYS:
        if not data.get(build):
            continue
        log(translate("writing", build=build))
        try:
            environment = UnityPy.load(base64.b64decode(data[build]))
        except Exception as exc:
            log(translate("decode_failed", build=build, error=exc))
            continue
        changed = 0
        for obj in environment.objects:
            if obj.type.name != "MonoBehaviour":
                continue
            try:
                tree = obj.read_typetree()
                if not tree:
                    continue

                def replace(node: object, path: str = "") -> None:
                    nonlocal changed
                    if isinstance(node, dict):
                        for key, value in list(node.items()):
                            child = f"{path}.{key}" if path else str(key)
                            if isinstance(value, str):
                                if key == "Author":
                                    # 先翻译 Author 原文，再在结尾追加作者名（避免“吞掉翻译”）
                                    if not is_exclude_word(value) and value in translations:
                                        node[key] = translations[value]
                                        changed += 1
                                    if author and author not in node[key]:
                                        node[key] = node[key] + author
                                        changed += 1
                                elif (not is_exclude_word(value) and value in translations
                                      and value not in OFFICIAL_LOC_KEYS):
                                    # 官方翻译 key 不写回：老版本提取的 JSON 可能混入，
                                    # 写回去游戏查表失败会显示 NULL
                                    node[key] = translations[value]
                                    changed += 1
                            elif isinstance(value, (dict, list)):
                                replace(value, child)
                    elif isinstance(node, list):
                        for index, value in enumerate(node):
                            child = f"{path}[{index}]"
                            if (isinstance(value, str) and not is_exclude_word(value)
                                    and value in translations and value not in OFFICIAL_LOC_KEYS):
                                node[index] = translations[value]
                                changed += 1
                            elif isinstance(value, (dict, list)):
                                replace(value, child)

                replace(tree)
                obj.save_typetree(tree)
            except Exception:
                continue
        try:
            data[build] = base64.b64encode(environment.file.save(packer="lzma")).decode("utf-8")
            log(translate("write_done", build=build, count=changed))
        except Exception as exc:
            log(translate("save_failed", build=build, error=exc))
    output = Path(input_file).with_name(f"{Path(input_file).stem}-CN.pack")
    try:
        output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log(translate("pack_done", path=output))
    except OSError as exc:
        log(translate("output_failed", error=exc))


def human_size(num: float) -> str:
    """把字节数格式化为人类可读的 B / KB / MB / GB。"""
    step = 1024.0
    size = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if size < step or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= step
    return f"{size:.1f} GB"


def decode_build_payload(build_value: object) -> bytes | None:
    """从 .pack 的某个平台 Build 字段解码 UnityFS 字节流。

    空串/纯空白也按"不存在"处理：b64decode("") 会返回 b"" 而不是报错，
    若把空值平台当"存在"保留，剥出来的包会带一个游戏加载不了的空平台块
    （实测有些包的字段就存在但值为空，如 CodeAssembly）。
    """
    if not isinstance(build_value, str):
        return None
    try:
        payload = base64.b64decode(build_value)
    except (ValueError, TypeError):
        return None
    return payload if payload else None


def count_bundle_parts(payload: bytes) -> int:
    """数 bundle 里有多少个部件：一个部件 = 一个 prefab 根对象。

    不能拿 MonoBehaviour 计数：一个零件上挂着 ResourceModule、RenderSortingModule
    等好几个组件，那样数出来会是真实部件数的好几倍。这里数 m_Father 为空的
    Transform 对应的 GameObject，也就是 prefab 的根。
    """
    try:
        environment = UnityPy.load(payload)
    except Exception:
        return 0
    transforms = [obj for obj in environment.objects if obj.type.name in ("Transform", "RectTransform")]
    roots: set[object] = set()
    for obj in transforms:
        try:
            tree = obj.read_typetree()
        except Exception:
            continue
        if not isinstance(tree, dict):
            continue
        father = tree.get("m_Father")
        if isinstance(father, dict):
            if (father.get("m_FileID") or 0) != 0 or (father.get("m_PathID") or 0) != 0:
                continue  # 有父节点 = 不是根
        else:
            continue
        game_object = tree.get("m_GameObject")
        if isinstance(game_object, dict) and game_object.get("m_PathID"):
            roots.add(game_object["m_PathID"])
        else:
            roots.add(obj.path_id)
    if roots:
        return len(roots)
    # 拿不到 typetree 时退化成 GameObject 总数，至少不至于报 0
    return sum(1 for obj in environment.objects if obj.type.name == "GameObject")


def analyze_pack(input_file: str, translate, log, progress=None) -> None:
    """概览 .pack：总体积、各平台 Build 解压体积与部件数量。

    progress：可选回调 progress(fraction)，逐平台推进（解码最慢的就是它）。
    """
    if not input_file:
        log(translate("strip_no_pack"))
        return
    if progress:
        progress(0.05, "progress_analyze")
    try:
        data = json.loads(Path(input_file).read_text(encoding="utf-8-sig"))
    except Exception as exc:
        log(translate("strip_read_fail", error=exc))
        return
    log(translate("analyzing"))
    content = Path(input_file).stat().st_size
    log(translate("pack_size", content=Path(input_file).name, size=human_size(content)))
    assembly = data.get("CodeAssembly")
    if isinstance(assembly, str) and assembly.strip():
        try:
            log(translate("assembly", size=human_size(len(base64.b64decode(assembly, validate=False)))))
        except Exception:
            log(translate("assembly", size=human_size(len(assembly))))
    else:
        log(translate("assembly_absent"))
    total = 0
    build_count = 0
    part_total = 0
    # 进度按"非空平台"的序号推进（解码耗时几乎都在这些 bundle 上）；
    # 但遍历仍走全部平台，空值/坏 base64 的平台必须照样打出 build_absent，
    # 否则包信息里会凭空少几行，用户看不出这个平台到底有没有。
    candidates = [k for k in BUILD_ORDER if isinstance(data.get(k), str) and data.get(k).strip()]
    for key in BUILD_ORDER:
        payload = decode_build_payload(data.get(key))
        if payload is None:
            log(translate("build_absent", plat=PLATFORM_NAMES.get(key, key)))
            continue
        build_count += 1
        total += len(payload)
        parts = count_bundle_parts(payload)
        # 各平台装的是同一批部件，取最大值而不是累加，否则“共 N 个部件”会被乘上平台数
        part_total = max(part_total, parts)
        log(translate("build_present", plat=PLATFORM_NAMES.get(key, key), size=human_size(len(payload)), parts=parts))
        if progress and candidates:
            progress(0.1 + 0.85 * (candidates.index(key) + 1) / len(candidates), "progress_analyze")
    if progress:
        progress(1.0, "analyze_done")
    log(translate("analyze_done", builds=build_count, parts=part_total, total=human_size(total)))


def strip_pack(input_file: str, output_file: str, platform_keys, translate, log, progress=None) -> None:
    """剥离到目标平台：只保留 platform_keys 中的平台与 CodeAssembly，删除其他平台 Build。

    剥离前先扫描包信息（剥离校验）：
    • 所选平台全都不在包里 → 直接拒绝，绝不写出一个不含任何平台的 .pack；
    • 部分不在包里 → 警告并只保留实有的平台；
    • 结果至少保留一个平台 + CodeAssembly。

    progress：可选回调 progress(fraction, label_key)，用于把进度条接到剥离流程上。
    """
    if not input_file:
        log(translate("strip_no_pack"))
        return
    if isinstance(platform_keys, str):
        platform_keys = [platform_keys]
    wanted = [k for k in BUILD_ORDER if k in set(platform_keys)]
    if not wanted:
        log(translate("strip_fail", error="未指定任何有效平台"))
        return
    if progress:
        progress(0.15, "progress_step_scan")
    try:
        data = json.loads(Path(input_file).read_text(encoding="utf-8-sig"))
    except Exception as exc:
        log(translate("strip_read_fail", error=exc))
        return
    # ---- 剥离前扫描：包内实有平台与体积 ----
    present = [k for k in BUILD_ORDER if decode_build_payload(data.get(k)) is not None]
    present_txt = "、".join(PLATFORM_NAMES.get(k, k) for k in present) if present else "无"
    log(translate("strip_scan_header", builds=len(present), list=present_txt))
    for key in present:
        payload = decode_build_payload(data.get(key))
        log(translate("strip_scan_plat", plat=PLATFORM_NAMES.get(key, key), size=human_size(len(payload))))
    # ---- 校验：保证剥离结果至少包含一个平台 ----
    keep = [k for k in wanted if k in present]
    if not keep:
        # 所选平台全都不在包里时，直接放弃：否则会写出一个只有 CodeAssembly、
        # 游戏根本加载不了的 .pack，而界面上还显示“剥离完成”。
        wanted_txt = "、".join(PLATFORM_NAMES.get(k, k) for k in wanted)
        log(translate("strip_no_target", wanted=wanted_txt, present=present_txt))
        return
    missing = [k for k in wanted if k not in present]
    if missing:
        missing_txt = "、".join(PLATFORM_NAMES.get(k, k) for k in missing)
        kept_txt = "、".join(PLATFORM_NAMES.get(k, k) for k in keep)
        log(translate("strip_missing_warn", missing=missing_txt, kept=kept_txt))
    if output_file:
        try:
            if Path(output_file).resolve() == Path(input_file).resolve():
                log(translate("strip_output_is_input"))
                return
        except OSError:
            pass
    log(translate("strip_start"))
    if progress:
        progress(0.45, "progress_step_strip_trim")
    removed = []
    kept = []
    for key in list(data.keys()):
        if key == "CodeAssembly":
            kept.append(key)
            continue
        if key in PLATFORM_KEYS and key not in keep:
            removed.append(PLATFORM_NAMES.get(key, key))
            data.pop(key, None)
        elif key in keep:
            kept.append(key)
    for name in removed:
        log(translate("strip_removed", plat=name))
    for name in kept:
        log(translate("strip_keep", plat=PLATFORM_NAMES.get(name, name)))
    if not output_file:
        suffix = "+".join(PLATFORM_NAMES.get(k, k) for k in keep)
        output_file = str(Path(input_file).with_name(f"{Path(input_file).stem}-{suffix}.pack"))
    if progress:
        progress(0.75, "progress_step_strip_write")
    try:
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        Path(output_file).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        log(translate("strip_fail", error=exc))
        return
    if progress:
        progress(1.0, "strip_done")
    log(translate("strip_done", out=output_file, size=human_size(Path(output_file).stat().st_size)))


# ---------------------------------------------------------------------------
# 缓存扫描 / 清理
# ---------------------------------------------------------------------------
def _dir_size(path: Path) -> int:
    """目录占用字节数（软链接/无权限项跳过）。"""
    total = 0
    try:
        for entry in path.rglob("*"):
            try:
                if entry.is_file() and not entry.is_symlink():
                    total += entry.stat().st_size
            except OSError:
                continue
    except OSError:
        return total
    return total


def scan_cache(toolkit_dir: str = "") -> list[dict]:
    """扫描可清理的缓存，返回 [{key, label_key, path, size, risky}]。

    分两类：临时/可再生（安全）与重要数据（★，清理后不可恢复，默认不勾选）。
    """
    items: list[dict] = []
    temp_root = Path(tempfile.gettempdir())

    stage = temp_root / "SFS_Pack_Stage"
    if stage.is_dir():
        items.append({"key": "stage", "label_key": "cache_item_stage",
                      "path": stage, "size": _dir_size(stage), "risky": False})

    # AssetRipper 导出用的 sfs_prefab_export_* 临时目录，正常会自动删；
    # 崩溃/强杀时会残留，占用往往最大
    leftovers = []
    try:
        leftovers = [p for p in temp_root.glob("sfs_prefab_export_*") if p.is_dir()]
    except OSError:
        leftovers = []
    if leftovers:
        size = sum(_dir_size(p) for p in leftovers)
        items.append({"key": "tmp", "label_key": "cache_item_tmp",
                      "path": temp_root, "size": size, "risky": False,
                      "targets": leftovers})

    runtime_dir = (Path(sys.executable).resolve().parent
                   if getattr(sys, "frozen", False)
                   else Path(__file__).resolve().parent)
    ripper = runtime_dir / ".assetripper"
    if ripper.is_dir():
        items.append({"key": "ripper", "label_key": "cache_item_ripper",
                      "path": ripper, "size": _dir_size(ripper), "risky": False})

    if toolkit_dir:
        tk = Path(toolkit_dir)
        dedupe_dirs = [p for p in tk.rglob("_DEDUPE_BACKUP") if p.is_dir()]
        if dedupe_dirs:
            items.append({"key": "dedupe", "label_key": "cache_item_dedupe",
                          "path": dedupe_dirs[0], "size": sum(_dir_size(p) for p in dedupe_dirs),
                          "risky": True, "targets": dedupe_dirs})
        backup = tk / "_PackToolBackup"
        if backup.is_dir():
            items.append({"key": "backup", "label_key": "cache_item_backup",
                          "path": backup, "size": _dir_size(backup), "risky": True})

    dist_backup = runtime_dir / "dist" / "_backup"
    if dist_backup.is_dir():
        items.append({"key": "dist", "label_key": "cache_item_dist",
                      "path": dist_backup, "size": _dir_size(dist_backup), "risky": True})
    return items


def clean_cache_items(items: list[dict], keys: set[str]) -> tuple[int, list[str]]:
    """删除选中的缓存项，返回 (释放字节, 失败说明列表)。"""
    freed = 0
    errors: list[str] = []
    for item in items:
        if item["key"] not in keys:
            continue
        targets = item.get("targets") or [item["path"]]
        for target in targets:
            try:
                size = _dir_size(target)
                shutil.rmtree(target, ignore_errors=False)
                freed += size
            except FileNotFoundError:
                continue
            except OSError as exc:
                errors.append(f"{target.name}: {exc}")
    return freed, errors




# ---------------------------------------------------------------------------
# 弹窗注入点
# ---------------------------------------------------------------------------
# 业务流程里到处是 messagebox.showinfo(...) 这类调用。为了把这段代码原样搬到
# 无界面层，这里提供一个同名的 shim：界面启动时把真正的实现注入进来，没注入时
# 退化成打印——保证模块能被单独 import（测试、CLI）。
_UI_HOOKS: dict[str, object] = {
    "info": lambda title, message: print(f"[info] {title}: {message}"),
    "warning": lambda title, message: print(f"[warn] {title}: {message}"),
    "error": lambda title, message: print(f"[error] {title}: {message}"),
    # 没有界面时**一律当作取消**：宁可让操作不执行，也不能在无人确认时把文件改了
    "askyesno": lambda title, message: False,
}


def set_ui_hooks(**hooks) -> None:
    """注入弹窗实现（info / warning / error / askyesno）。"""
    for key, func in hooks.items():
        if key in _UI_HOOKS and callable(func):
            _UI_HOOKS[key] = func


class _MessageBoxShim:
    """模仿 tkinter.messagebox 的最小接口，业务代码无需改动。"""

    @staticmethod
    def showinfo(title, message="", **_kw):
        _UI_HOOKS["info"](title, message)

    @staticmethod
    def showwarning(title, message="", **_kw):
        _UI_HOOKS["warning"](title, message)

    @staticmethod
    def showerror(title, message="", **_kw):
        _UI_HOOKS["error"](title, message)

    @staticmethod
    def askyesno(title, message="", **_kw) -> bool:
        return bool(_UI_HOOKS["askyesno"](title, message))

    askokcancel = askyesno


messagebox = _MessageBoxShim()



# ---------------------------------------------------------------------------
# 业务逻辑 mixin
# ---------------------------------------------------------------------------
class LogicMixin:
    """导出工程 / 并入 Toolkit / 各类弹窗文案。

    依赖宿主（App）提供的这些东西：
      self.t(key, **kw)      中英文案
      self.log(text)         日志
      self.tlog(text)        日志（英文模式下自动翻译）
      self._ui(fn)           把回调丢回主线程
      self.set_progress(f, l) 进度条
      self.input_file        当前选中的 .pack
      self.toolkit_dir_var / self.package_dir_var / self.install_var
    """

    def _asset_ripper_version_setting(self) -> str | None:
        """设置页里选的 AssetRipper 版本；用内置版时返回 None。"""
        if self.settings.get("asset_ripper_mode") != "version":
            return None
        ver = str(self.settings.get("asset_ripper_version", "") or "").strip()
        return ver or None
    def _asset_ripper_path_setting(self) -> str | None:
        """设置页里手动指定的 AssetRipper 可执行文件；未指定返回 None。"""
        if self.settings.get("asset_ripper_mode") != "custom":
            return None
        path = str(self.settings.get("asset_ripper_path", "") or "").strip()
        return path or None
    @staticmethod
    def _exported_part_names(export_dir: Path) -> list[str]:
        """本次导出产生的部件名（prefab 去扩展名），用于增量判断"部件是否还在"。

        只看导出工程里的部件目录，不扫整个 Toolkit —— 扫整个 Toolkit 会把别人
        的部件也算进来，导致「部件仍在」这个判据永远成立、增量判断失效。
        """
        parts: set[str] = set()
        try:
            for prefab in Path(export_dir).rglob("*.prefab"):
                parts.add(prefab.stem)
        except OSError:
            pass
        return sorted(parts)
    def _export_index_path(self) -> Path:
        """增量重导出索引：记录每个包上次导出的指纹与部件清单。"""
        return app_data_dir() / "export_index.json"
    def _export_one(self, pack: Path, log, output: Path | None = None) -> None:
        """单个包的完整导出流程（批量模式复用）。

        与 start_export 的区别：不碰 GUI 状态（导出按钮、忙碌锁、增量判断），
        只跑「清暂存 → export_project → repair_toolkit」。export_project 内部大量
        使用 self.input_file，所以这里临时切换并在 finally 里还原。
        """
        stage_root = Path(tempfile.gettempdir()) / "SFS_Pack_Stage"
        stage_root.mkdir(parents=True, exist_ok=True)
        out = Path(output) if output else stage_root / f"{pack.stem}_export"
        toolkit_dir = self.toolkit_dir_var.get().strip()
        previous = getattr(self, "input_file", "")
        self.input_file = str(pack)
        try:
            shutil.rmtree(out, ignore_errors=True)
            self.export_project(log, str(out), toolkit_dir, bool(self.install_var.get()))
            self.repair_toolkit(log, toolkit_dir, self.package_dir_var.get().strip())
        finally:
            self.input_file = previous
    def repair_toolkit(self, log, toolkit_dir: str, package_dir: str = "") -> None:
        log(self.t("repair_start"))
        try:
            import sfs_pack_core as keepalive
            keepalive.log = self.tlog
            rep = keepalive.repair_toolkit_shaders(Path(toolkit_dir), log=self.tlog, backup=True)
        except Exception as exc:
            log(self.t("processing_failed", error=exc))
            rep = {}
        if rep.get("stubs", 0) or rep.get("names_fixed", 0):
            log(self.t("repair_done", stubs=rep.get("stubs", 0), refs=rep.get("refs", 0),
                       names=rep.get("names_fixed", 0), backup=rep.get("backup_dir", "")))
        else:
            log(self.t("repair_none"))

        # 悬空引用自愈扫描（提供原始 mod 工程目录可自动修复，否则只扫描+清单）
        try:
            drep = keepalive.repair_toolkit_dangling_refs(
                Path(toolkit_dir), package_assets=package_dir or None, log=self.tlog, backup=True)
        except Exception as exc:
            log(self.t("processing_failed", error=exc))
            return
        if drep.get("dangling", 0) == 0:
            log(self.t("repair_dangling_none"))
        else:
            log(self.t("repair_dangling_clean", redirected=drep.get("redirected", 0),
                       imported=drep.get("imported", 0), unresolved=drep.get("unresolved", 0)))
    def export_project(self, log, output: str, toolkit_dir: str = "", install: bool = False) -> None:
        # 确定进度分 7 段，按实际耗时分配权重（AssetRipper 导出最慢占大头）
        steps = [
            (0.05, "progress_step_scan"),
            (0.45, "progress_step_ripper"),
            (0.55, "progress_step_align"),
            (0.65, "progress_step_shader"),
            (0.72, "progress_step_dedupe"),
            (0.80, "progress_step_merge"),
            (0.92, "progress_step_packdata"),
        ]
        step_index = 0

        def advance() -> None:
            nonlocal step_index
            if step_index < len(steps):
                frac, key = steps[step_index]
                self.set_progress(frac, self.t(key))
                step_index += 1

        advance()
        log(self.t("export_start"))
        # 硬性约定：解包前先扫一遍包信息（平台包是否齐全 / 是否带自定义脚本 dll / 依赖哪个版本），
        # 先知道包里有什么、再决定走哪条路线，避免导入后才发现脚本挂空、来回返工。
        try:
            import sfs_pack_core as keepalive
            keepalive.log = self.tlog
            scan = keepalive.scan_pack(
                Path(self.input_file),
                Path(toolkit_dir) if toolkit_dir and Path(toolkit_dir).is_dir() else None,
                log=self.tlog,
            )
            # P1-1：自定义类判定退化时必须让用户看见（不是埋进日志就算数）。
            #       代码侧已经守住铁律（拿不准就不删），所以这是可观测性而非安全修复。
            # P2-1：包里带自定义脚本却没装 ilspycmd 时，明确告诉用户去哪儿装。
            self._after_scan_notices(scan, log)
        except Exception as exc:
            log(self.t("log_scan_fail", exc=exc))
        args = SimpleNamespace(
            input=self.input_file, output_dir=output, zip=None,
            asset_ripper=self._asset_ripper_path_setting(),
            asset_ripper_version=self._asset_ripper_version_setting(),
            # 默认用内置版（不联网）；用户显式指定版本或路径时才允许下载，
            # 否则"指定版本"永远会因 no_download 而失败（复审发现的真实 bug）。
            no_download=not (self._asset_ripper_version_setting()
                             or self._asset_ripper_path_setting()),
            no_zip=False, overwrite=True)
        previous_log = prefab_exporter.log
        # 走 tlog 而不是原始 log：英文模式下导出器内部的中文日志也会一并翻成英文
        prefab_exporter.log = self.tlog
        advance()
        try:
            exported_dir = Path(prefab_exporter.export_prefabs(args))
        except Exception as exc:
            log(self.t("export_failed", error=exc))
            return
        finally:
            prefab_exporter.log = previous_log

        merge_dir = exported_dir.with_name(f"{exported_dir.name}_新增合并包")
        mrep: dict[str, object] = {}
        # 合并闸门：脚本引用还没接上就绝不允许灌进 Toolkit，否则 Unity 满屏 Script is missing
        gate_blocked = False
        gate_report: dict[str, dict[str, object]] = {}

        # 1) 脚本免挂对齐
        if toolkit_dir and Path(toolkit_dir).is_dir():
            advance()
            try:
                import sfs_pack_core as keepalive
                keepalive.log = self.tlog
                report = keepalive.align_scripts_to_toolkit(
                    exported_dir,
                    Path(self.input_file),
                    Path(toolkit_dir),
                    log=self.tlog,
                )
                if report.get("ok"):
                    log(self.t("log_align_done", rewritten=report.get('rewritten_prefabs', 0), refs=report.get('rewritten_refs', 0)))
                    gate_report = report.get("unresolved_guids") or {}
                else:
                    log(self.t("log_align_skip", error=report.get('error')))
            except Exception as exc:
                log(self.t("log_align_fail", exc=exc))

            # 1.5) 自动处理“黑板”：把 AssetRipper 空壳着色器就地换成 Toolkit 真源码
            advance()
            try:
                import sfs_pack_core as keepalive
                srep = keepalive.fix_stub_shaders(
                    exported_dir / "Assets", Path(toolkit_dir), log=self.tlog, mode="copy"
                )
                if srep.get("stubs"):
                    log(self.t("shader_fixed", n=srep["stubs"]))
                    if srep.get("unmatched"):
                        log(self.t("shader_unmatched", n=len(srep["unmatched"]), names=sorted(set(srep["unmatched"]))))
            except Exception as exc:
                log(self.t("log_shader_fail_export", exc=exc))

            # 1.8) 把模组自己带的资产归拢到 <模组名>/{Audio,Sticker,Prefab,Other}
            #     只整理导出工程；合并进 Toolkit 时部件仍会归一化到 Resources/Parts，不影响出包。
            try:
                import sfs_pack_core as keepalive
                keepalive.log = self.tlog
                oreps = keepalive.organize_mod_assets(
                    exported_dir / "Assets",
                    keepalive.mod_folder_name(Path(self.input_file)),
                    log=self.tlog,
                )
                if oreps.get("error"):
                    log(self.t("log_organize_skip", error=oreps.get("error")))
            except Exception as exc:
                log(self.t("log_organize_fail", exc=exc))

            # 1.85) 工程内去重：移除 X 与 X_0 这类"同物异名"的重复导出资产
            #      （暂存目录复用 / 包内同名重复都会产生），引用统一改指保留的那份
            advance()
            try:
                import sfs_pack_core as keepalive
                keepalive.dedupe_export_assets(
                    exported_dir / "Assets", log=self.tlog,
                    backup_dir=exported_dir / "_DEDUPE_BACKUP")
            except Exception as exc:
                log(self.t("log_dedupe_fail", exc=exc))

            # 1.86) [实验] 1.7（Propulsion-Rebase）引擎自动修复：给旧 mod 的引擎/助推器
            #       补齐 heatHitbox / isVacuum / multipleNozzles / heatHitboxes / boosterOn 等
            #       新字段（仅当设置里打开「实验：1.7 引擎自动修复」时运行）
            if self.settings.get("repair_engine_17", False):
                advance()
                try:
                    import sfs_pack_core as keepalive
                    rrep = keepalive.repair_engine_modules_for_17(
                        exported_dir / "Assets", Path(toolkit_dir), log=self.tlog,
                        backup_dir=exported_dir / "_ENGINE17_BACKUP")
                    if rrep.get("skip"):
                        log(self.t("repair17_skip"))
                except Exception as exc:
                    log(self.t("repair17_fail", exc=exc))

            # 1.9) 合并闸门：仍有脚本 GUID 在工程里查无此人 → 拒绝合并并落排查清单
            if gate_report:
                gate_blocked = True
                refs = sum(int(r.get("count", 0)) for r in gate_report.values())
                classes = sorted({str(r.get("class") or "(未知)") for r in gate_report.values()})
                log(self.t("log_gate_blocked", n=len(gate_report), refs=refs))
                log(self.t("log_gate_classes", classes=", ".join(classes[:12]) + ("..." if len(classes) > 12 else "")))
                try:
                    import sfs_pack_core as keepalive
                    rpt = keepalive.write_unresolved_report(
                        exported_dir / "UNRESOLVED_SCRIPTS.md", gate_report)
                    log(self.t("log_gate_stop", path=str(rpt)))
                    self._gate_popup(len(gate_report), refs, classes, str(rpt))
                except Exception as exc:
                    log(f"[GATE] report failed: {exc}")

            # 2) 纯新增合并包（闸门拦下时整段跳过，不生成合并包）
            if gate_blocked:
                log(self.t("log_merge_none", error=self.t("log_gate_title")))
            else:
                advance()
                try:
                    import sfs_pack_core as keepalive
                    keepalive.log = self.tlog
                    mrep = keepalive.build_merge_package(
                        exported_dir,
                        Path(self.input_file),
                        Path(toolkit_dir),
                        merge_dir,
                        log=self.tlog,
                    )
                    if mrep.get("ok"):
                        log(self.t("log_merge_done", pkg=mrep['package_dir'], new=mrep['new_parts'], skip=mrep['skipped_parts'], copy=mrep['copied_files']))
                    else:
                        log(self.t("log_merge_none", error=mrep.get('error')))
                except Exception as exc:
                    log(self.t("log_merge_fail", exc=exc))

            # 3) 可选：并入 Toolkit。默认关闭；开启时绝不覆盖内容正常的既有文件，
            #    但会对"已存在却引用悬空"的资产做修复性覆盖（先备份）。
            #    注意这里不能再用 new_parts 做门槛：部件全都已存在时 new_parts=0，
            #    而那份已存在的 prefab 恰恰可能正是引用悬空、需要被修好的那个。
            if mrep.get("ok"):
                if not install:
                    log(self.t("install_skipped_opt"))
                else:
                    advance()
                    merged = self.install_into_toolkit(
                        log, Path(toolkit_dir), Path(str(mrep["package_dir"])), mrep)
                    # 2.5) 自动生成 PackData 资产 + 统一 AssetBundle 标签：
                    #      并入后用户在 Unity 的 ModBuilder 里选资产+标签即可一键出包
                    #      并入被拒（同名程序集冲突，一个文件都没写）时不能盖章：
                    #      Toolkit 里还没有这个模组的任何东西，盖出来是个空出包入口。
                    advance()
                    if not merged:
                        log(self.t("packdata_skipped_refused"))
                    else:
                        try:
                            import sfs_pack_core as keepalive
                            mod_name = keepalive.mod_folder_name(Path(self.input_file))
                            prep = keepalive.generate_pack_data(
                                Path(toolkit_dir), Path(self.input_file), mod_name, log=self.tlog)
                            if prep.get("ok"):
                                log(self.t("packdata_done", path=prep.get("packdata", ""),
                                           labeled=prep.get("labeled", 0), label=mod_name))
                        except Exception as exc:
                            log(self.t("packdata_fail", error=exc))

            # 4) 导出后自检：校验导出工程所有 prefab 的脚本引用是否在 Toolkit 命中
            try:
                import sfs_toolkit_script_check as prefab_verify
                guid_map = prefab_verify.build_script_guid_map(Path(toolkit_dir) / "Assets" / "Scripts")
                # mod 自有脚本(DLL/ModCode)的 guid 不在 Toolkit 内，但已保留在导出工程，
                # 纳入自检范围，避免自定义引用被误判为『缺失』
                try:
                    guid_map.update(prefab_verify.build_plugin_guid_map(exported_dir / "Assets"))
                except Exception:
                    pass
                total_refs = total_missing = 0
                missing_files: list[str] = []
                for prefab in (exported_dir / "Assets").rglob("*.prefab"):
                    res = prefab_verify.verify_prefab_script_refs(str(prefab), guid_map)
                    total_refs += res["total_refs"] if res["total_refs"] else 0
                    total_missing += res["missing"]
                    if res["missing"]:
                        missing_files.append(str(prefab.relative_to(exported_dir)))
                log(self.t("log_verify_hit", hit=total_refs - total_missing, total=total_refs, miss=total_missing))
                if total_missing:
                    log(self.t("log_verify_missing", n=len(missing_files), files=", ".join(missing_files[:8]) + ("..." if len(missing_files) > 8 else "")))
                    try:
                        with (merge_dir / "MERGE_README.md").open("a", encoding="utf-8") as fh:
                            fh.write(f"\n- 导出工程自检 {total_missing} 处脚本引用缺失 涉及 {len(missing_files)} 个 prefab 多为 mod 自定义类 需 CodeAssembly\n")
                    except OSError:
                        pass
            except Exception as exc:
                log(self.t("log_verify_fail", exc=exc))

        # 增量索引：记录本次导出（失败不影响本次结果）
        # 注意 record_export 的 parts 要的是**部件名列表**，不是数量；
        # 传数量会在 sorted() 里抛 TypeError，被这里吞掉 → 索引永远写不进去，
        # 增量导出就永远判定为「首次导出」。这是复审发现并修掉的真实 bug。
        try:
            import sfs_pack_toolbox as toolbox
            part_names = self._exported_part_names(exported_dir)
            fp = ""
            try:
                fp = toolbox.probe_toolkit_version(toolkit_dir).get("fingerprint", "")
            except Exception:
                fp = ""
            toolbox.record_export(
                self._export_index_path(), Path(self.input_file),
                parts=part_names, toolkit_fingerprint=fp,
                extra={"installed": bool(install)})
            log(self.t("incremental_recorded", n=len(part_names)))
        except Exception as exc:
            log(self.t("incremental_record_fail", error=exc))

        self.set_progress(1.0, self.t("export_done"))
        log(self.t("export_done"))
    def _after_scan_notices(self, scan: dict, log) -> None:
        """扫描后的两条用户须知（P1-1 判定退化 / P2-1 缺 ilspycmd）。

        都是"不阻断导出、但用户必须知道"的事，所以只在真发生时各弹一次窗，
        并在日志里同步留一行，方便事后翻日志复盘。
        """
        # P1-1：custom_source 退化成"减法口径"或"未判定"时给出醒目提示
        if not scan.get("custom_reliable", True):
            reason = str(scan.get("custom_reason") or "未知原因")
            source = str(scan.get("custom_source") or "未判定")
            log(self.t("scan_unreliable_log", reason=reason, source=source))
            try:
                self._ui(lambda: messagebox.showwarning(
                    self.t("scan_unreliable_title"),
                    self.t("scan_unreliable_body", reason=reason, source=source)))
            except Exception:
                pass
        # P2-1：包带自定义脚本 dll 但机器上没有 ilspycmd → 明确告诉用户怎么装
        ca = scan.get("code_assembly") or {}
        if ca.get("present") and ca.get("is_pe"):
            try:
                import sfs_pack_core as keepalive
                has_ilspy = bool(keepalive.find_ilspy())
            except Exception:
                has_ilspy = True
            if not has_ilspy:
                try:
                    self._ui(lambda: messagebox.showinfo(
                        self.t("scan_ilspy_title"), self.t("scan_ilspy_body")))
                except Exception:
                    pass
    def _gate_popup(self, n: int, refs: int, classes: list[str], path: str) -> None:
        """闸门弹窗。导出跑在工作线程里，必须丢回 Tk 主线程再弹。"""
        body = self.t("log_gate_body", n=n, refs=refs,
                      classes="\n".join(f"• {c}" for c in classes[:12])
                      + ("\n..." if len(classes) > 12 else ""),
                      path=path)
        title = self.t("log_gate_title")
        try:
            self._ui(lambda: messagebox.showwarning(title, body))
        except Exception:
            pass
    def _assembly_conflict_popup(self, conflicts: list[dict], package_dir: Path) -> None:
        """同名程序集冲突弹窗（方案 A / P0-1）。同 _gate_popup：得回主线程弹。"""
        body = self.t("install_asm_conflict_body",
                      list=format_asm_conflicts(conflicts), path=str(package_dir))
        title = self.t("install_asm_conflict_title")
        try:
            self._ui(lambda: messagebox.showwarning(title, body))
        except Exception:
            pass
    def _asm_scan_failed_popup(self, package_dir: Path) -> None:
        """预检自身出错时的弹窗：说明这是「判不准所以保守拒绝」，不是发现了冲突。"""
        title = self.t("install_asm_conflict_title")
        body = self.t("install_asm_conflict_scan_fail_body", path=str(package_dir))
        try:
            self._ui(lambda: messagebox.showwarning(title, body))
        except Exception:
            pass
    def _source_conflict_popup(self, conflicts: list[dict], package_dir: Path) -> None:
        """源码撞名（CS0101）弹窗（P1-2）：点名是哪个类、哪两个文件。"""
        lines = [
            f"• {c['type']}\n    本次：{c['incoming']}\n    既有：{c['existing']}"
            for c in conflicts[:8]
        ]
        if len(conflicts) > 8:
            lines.append("...")
        body = self.t("install_src_conflict_body", list="\n".join(lines), path=str(package_dir))
        title = self.t("install_src_conflict_title")
        try:
            self._ui(lambda: messagebox.showwarning(title, body))
        except Exception:
            pass
    def install_into_toolkit(self, log, toolkit_dir: Path, package_dir: Path, mrep: dict[str, object]) -> bool:
        """把合并包并入 Toolkit。

        返回 False = **并入被拒**（同名程序集冲突，一个文件都没写进 Toolkit），
        调用方据此跳过 PackData 盖章——没并进去还盖个出包入口等于骗用户。
        其余情况（含闸门 GUID 冲突那种只报不写的）返回 True，保持原行为。

        默认只写新文件、绝不覆盖既有内容。两个例外（都会先备份到
        `<Toolkit>/_PackToolBackup/<时间戳>/`）：

        1. **GUID 过期占位**：Toolkit 里已有同名文件，但它的 GUID 不是本次要装的
           prefab 所引用的那个，而包里这份才是 —— 说明那是上一轮导入留下的旧版本
           （贴图/材质挂空的典型根因：prefab 指新 GUID，磁盘上是旧 GUID）。
        2. **悬空引用修复**：同名资产引用大量悬空，而包里这份悬空更少。

        判据都是"只会往好的方向改"，不会把好的改坏。

        动手之前先过一道**同名程序集预检**（P0-1 方案 A）：Toolkit 里若已有内容
        不同的同名 dll，就地拒绝整个并入并弹窗点名两个模组。少了这一步，后装的
        模组会经「例外 1」静默顶掉先装的 dll，先装模组的部件脚本全部 missing
        script，而日志只有一行"已替换 N 个同名残留"，看不出出了事。
        """
        collisions = mrep.get("guid_collisions") or []
        if collisions:
            log(self.t("install_refused", n=len(collisions)))
            return True  # 闸门分支另有处理，这里保持原行为：只报不写
        pkg_assets = package_dir / "Assets"
        tk_assets = toolkit_dir / "Assets"
        if not pkg_assets.is_dir():
            return True

        # 悬空判断用的已知 GUID 全集：Toolkit 现有的 + 包内带的
        import sfs_pack_core as keepalive

        # --- P0-1 预检：一个文件都还没写，先看会不会撞掉别人的程序集 ---
        try:
            asm_conflicts = keepalive.detect_assembly_conflicts(
                toolkit_dir, package_dir, str(mrep.get("parts_subfolder", "") or ""))
        except Exception as exc:
            # 预检自己出错 = 判不准。这道闸门防的就是"静默顶掉别人的程序集"，
            # 判不准时宁可停下报错（并入本就是可选项，重试代价小），也不能
            # 放行去赌一把——赌输了先装那个模组的部件脚本就全挂了。
            log(self.t("install_asm_conflict_scan_fail", error=exc))
            try:
                self._asm_scan_failed_popup(package_dir)
            except Exception:
                pass
            return False
        if asm_conflicts:
            for c in asm_conflicts:
                log(self.t("install_asm_conflict_item",
                           name=c["name"], rel=c["rel"],
                           old_owner=c["existing_owner"] or "?", old_guid=c["existing_guid"] or "?",
                           new_owner=c["incoming_owner"] or "?", new_guid=c["incoming_guid"] or "?"))
            log(self.t("install_asm_conflict",
                       names=", ".join(c["name"] for c in asm_conflicts)))
            try:
                self._assembly_conflict_popup(asm_conflicts, package_dir)
            except Exception:
                pass
            return False  # 就地拒绝：一个文件都没写，合并包仍留在原处供人工处理

        # --- P1-2 预检：本次的 .cs 源码与 Toolkit 已有脚本撞同名类型 → Unity CS0101 ---
        # 这里与上面的程序集预检故意**反着来**：预检自身出错时放行，不拒绝。
        # 因为两者出错的后果不对称——程序集那条漏了会静默顶掉别人已装好的模组，
        # 而源码这条漏了最坏是 Unity 打开时报 CS0101（当场可见、用户自己就能修）。
        # 判不准就放行 + 打日志，比"因为一个预检 bug 拦住所有人并入"划算。
        try:
            src_conflicts = keepalive.detect_source_type_conflicts(toolkit_dir, package_dir)
        except Exception as exc:
            src_conflicts = []
            log(self.t("install_src_conflict_scan_fail", error=exc))
        if src_conflicts:
            for c in src_conflicts:
                log(self.t("install_src_conflict_item", **c))
            log(self.t("install_src_conflict", n=len(src_conflicts)))
            try:
                self._source_conflict_popup(src_conflicts, package_dir)
            except Exception:
                pass
            return False

        known: set[str] = set()
        for meta in tk_assets.rglob("*.meta"):
            g = keepalive._meta_guid(meta)
            if g:
                known.add(g)
        for meta in pkg_assets.rglob("*.meta"):
            g = keepalive._meta_guid(meta)
            if g:
                known.add(g)

        # 本次导入"真正需要的" GUID：包内所有 prefab/asset/材质文本里出现的引用。
        # Toolkit 里若有同名文件却挂着另一个 GUID，说明它是历史残留，必须让位。
        wanted: set[str] = set()
        for f in pkg_assets.rglob("*"):
            if not f.is_file() or f.suffix.lower() not in {".prefab", ".mat", ".asset",
                                                           ".controller", ".anim", ".unity"}:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for mm in keepalive.GUID_FIELD_RE.finditer(text):
                wanted.add(mm.group(1).lower())

        def _asset_guid(p: Path) -> str:
            """取资产文件的 GUID（.meta 自身或同名 .meta 里的）。"""
            if p.name.endswith(".meta"):
                return keepalive._meta_guid(p)
            m = Path(str(p) + ".meta")
            return keepalive._meta_guid(m) if m.is_file() else ""

        repairable_suffixes = {".prefab", ".mat", ".asset"}
        written = written_parts = skipped_existing = repaired = replaced_stale = 0
        backup_root = toolkit_dir / "_PackToolBackup" / time.strftime("%Y%m%d_%H%M%S")
        try:
            for src in sorted(pkg_assets.rglob("*")):
                if not src.is_file():
                    continue
                dest = tk_assets / src.relative_to(pkg_assets)
                if dest.exists():
                    if dest.is_file():
                        # 例外 1：GUID 过期占位。Toolkit 里同名文件的 GUID 不是本次要用的
                        # 那个（包内这份才是），说明它是上一轮导入留下的旧版本——贴图/材质
                        # 挂空多半就是这么来的（prefab 指新 GUID，磁盘上躺着旧 GUID）。
                        src_guid = _asset_guid(src)
                        dest_guid = _asset_guid(dest)
                        if (src_guid and dest_guid and src_guid != dest_guid
                                and src_guid in wanted):
                            try:
                                saved = backup_root / dest.relative_to(tk_assets)
                                saved.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(dest, saved)
                            except OSError:
                                pass  # 备份失败就不动它，宁可漏修不可误覆盖
                            else:
                                shutil.copy2(src, dest)
                                replaced_stale += 1
                                continue
                    # 例外 2：这份是"引用悬空"的坏资产，而包里这份更好
                    if dest.is_file() and src.suffix.lower() in repairable_suffixes:
                        try:
                            old_text = dest.read_text(encoding="utf-8", errors="ignore")
                            new_text = src.read_text(encoding="utf-8", errors="ignore")
                        except OSError:
                            skipped_existing += 1
                            continue
                        old_bad = keepalive.count_dangling_refs(old_text, known)
                        new_bad = keepalive.count_dangling_refs(new_text, known)
                        if old_bad and new_bad < old_bad:
                            try:
                                saved = backup_root / dest.relative_to(tk_assets)
                                saved.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(dest, saved)
                            except OSError:
                                pass  # 备份失败就不动它，宁可漏修不可误覆盖
                            else:
                                shutil.copy2(src, dest)
                                repaired += 1
                                log(self.t("install_repaired", name=dest.name, before=old_bad, after=new_bad))
                                continue
                    skipped_existing += 1
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                written += 1
                if src.suffix.lower() == ".prefab":
                    written_parts += 1
        except OSError as exc:
            log(self.t("install_failed", error=exc))
            return True  # 半途失败已报日志：不额外触发"被拒"分支的跳过逻辑
        if replaced_stale:
            log(self.t("install_replaced_stale", n=replaced_stale, path=backup_root))
        if repaired:
            log(self.t("install_repair_done", n=repaired, path=backup_root))
        if skipped_existing:
            log(self.t("install_skipped", n=skipped_existing))
        if written_parts:
            log(self.t("install_wrote_parts", n=written_parts, path=tk_assets))
            log(self.t("installed_to_toolkit", new=mrep.get("new_parts", 0), skip=mrep.get("skipped_parts", 0), copy=mrep.get("copied_files", 0), sub=mrep.get("parts_subfolder", "")))
        elif written:
            log(self.t("install_wrote_files", n=written, path=tk_assets))
        elif not (repaired or replaced_stale):
            log(self.t("install_nothing"))
        return True
