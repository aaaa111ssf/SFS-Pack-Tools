#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CS0101 去重兜底离线验证：模拟 AssetRipper stub 落在 Scripts/Assembly-CSharp 下。

场景复刻 PicoSpace Utility Pack 1.6.1 的报错：
  Assets/Scripts/Assembly-CSharp/SFS/Parts/Modules/ActivationSequenceModule.cs  (stub, 随机 GUID)
  Assets/Scripts/Parts/Utility/ActivationSequenceModule.cs                      (Toolkit 真脚本)
两份都声明 SFS.Parts.Modules.ActivationSequenceModule → CS0101。
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "sfs_pack_core.py"

STUB = """// AssetRipper 生成的 stub
using UnityEngine;

namespace SFS.Parts.Modules
{
    public class ActivationSequenceModule : MonoBehaviour
    {
        public int order;
    }
}
"""

REAL = """using UnityEngine;
using SFS.Parts.Modules;

namespace SFS.Parts.Modules
{
    public class ActivationSequenceModule : MonoBehaviour
    {
        public int order;
        public float delay;
    }
}
"""

PARTIAL_A = """namespace SFS.Parts.Modules
{
    public partial class AdaptModule : MonoBehaviour
    {
        void A() { }
    }
}
"""

PARTIAL_B = """namespace SFS.Parts.Modules
{
    public partial class AdaptModule : MonoBehaviour
    {
        void B() { }
    }
}
"""

PARTIAL_STUB = """namespace SFS.Parts.Modules
{
    public class AdaptModule : MonoBehaviour
    {
        void Stub() { }
    }
}
"""


def load_module():
    spec = importlib.util.spec_from_file_location("keep_alive", SRC)
    module = importlib.util.module_from_spec(spec)
    sys.modules["keep_alive"] = module
    spec.loader.exec_module(module)
    return module


def write(path: Path, text: str, guid: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    Path(str(path) + ".meta").write_text(
        f"fileFormatVersion: 2\nguid: {guid}\nMonoImporter:\n  externalObjects: {{}}\n",
        encoding="utf-8",
    )


def main() -> int:
    ka = load_module()
    temp = Path(tempfile.mkdtemp(prefix="sfs_dedupe_"))
    project = temp / "Export"
    toolkit = temp / "Toolkit"

    # Toolkit：只有真脚本
    write(toolkit / "Assets/Scripts/Parts/Utility/ActivationSequenceModule.cs", REAL, "a" * 32)
    write(toolkit / "Assets/Scripts/Parts/Interaction/AdaptModule.cs", PARTIAL_A, "b" * 32)
    write(toolkit / "Assets/Scripts/Parts/Interaction/AdaptModule.Helper.cs", PARTIAL_B, "c" * 32)

    # 导出工程：Toolkit 副本 + AssetRipper stub（按命名空间镜像路径）
    write(project / "Assets/Scripts/Parts/Utility/ActivationSequenceModule.cs", REAL, "a" * 32)
    write(project / "Assets/Scripts/Parts/Interaction/AdaptModule.cs", PARTIAL_A, "b" * 32)
    write(project / "Assets/Scripts/Parts/Interaction/AdaptModule.Helper.cs", PARTIAL_B, "c" * 32)
    write(
        project / "Assets/Scripts/Assembly-CSharp/SFS/Parts/Modules/ActivationSequenceModule.cs",
        STUB,
        "d" * 32,
    )
    write(
        project / "Assets/Scripts/Assembly-CSharp/SFS/Parts/Modules/AdaptModule.cs",
        PARTIAL_STUB,
        "e" * 32,
    )

    ok = 0
    fail = 0

    def check(label: str, cond: bool):
        nonlocal ok, fail
        print(f"  [{'OK ' if cond else 'FAIL'}] {label}")
        ok += bool(cond)
        fail += not cond

    logs: list[str] = []
    removed, conflicts = ka.dedupe_conflicting_scripts(
        project, toolkit, {"a" * 32, "b" * 32, "c" * 32}, logs.append
    )
    for line in logs:
        print("    " + line)

    print("\n=== 1. 重复类型清理 ===")
    check("删掉了 2 个重复定义", removed == 2)
    check("冲突类报告含 ActivationSequenceModule",
          any("ActivationSequenceModule" in c for c in conflicts))
    check("冲突类报告含 AdaptModule", any("AdaptModule" in c for c in conflicts))
    check("保留 Toolkit 真脚本 Parts/Utility",
          (project / "Assets/Scripts/Parts/Utility/ActivationSequenceModule.cs").is_file())
    check("删除 Assembly-CSharp 下的 stub",
          not (project / "Assets/Scripts/Assembly-CSharp/SFS/Parts/Modules/ActivationSequenceModule.cs").is_file())
    check("stub 的 .meta 一并删除",
          not (project / "Assets/Scripts/Assembly-CSharp/SFS/Parts/Modules/ActivationSequenceModule.cs.meta").is_file())

    print("\n=== 2. partial 分片不被误删 ===")
    check("AdaptModule.cs 保留", (project / "Assets/Scripts/Parts/Interaction/AdaptModule.cs").is_file())
    check("AdaptModule.Helper.cs 保留",
          (project / "Assets/Scripts/Parts/Interaction/AdaptModule.Helper.cs").is_file())
    check("Assembly-CSharp 下的非 partial 同名类被删",
          not (project / "Assets/Scripts/Assembly-CSharp/SFS/Parts/Modules/AdaptModule.cs").is_file())

    print("\n=== 3. 复查：不再有重复类型 ===")
    again, again_conf = ka.dedupe_conflicting_scripts(
        project, toolkit, {"a" * 32, "b" * 32, "c" * 32}, lambda _m: None
    )
    check("二次扫描零删除 幂等", again == 0 and not again_conf)

    print("\n=== 4. Toolkit 自带 stub 的跳过判定 ===")
    dirty = temp / "DirtyToolkit"
    # 真脚本 + 同名 Dummy stub 混在一起（复刻 Modding Toolkit12 的实际情况）
    write(dirty / "Assets/Scripts/Parts/Utility/ActivationSequenceModule.cs", REAL, "a" * 32)
    write(
        dirty / "Assets/Scripts/Assembly-CSharp/SFS/Parts/Modules/ActivationSequenceModule.cs",
        STUB.replace("// AssetRipper 生成的 stub", "// Dummy class. This could have happened for several reasons:"),
        "f" * 32,
    )
    # 只有 stub、没有真脚本的类：不能跳过，跳了会缺类
    write(
        dirty / "Assets/Scripts/Assembly-CSharp/SFS/Parts/Modules/OnlyStub.cs",
        "namespace SFS.Parts.Modules\n{\n    // Dummy class.\n    public class OnlyStub : MonoBehaviour { }\n}\n",
        "0" * 32,
    )
    skip = ka.stub_conflicts(dirty / "Assets" / "Scripts")
    names = {p.name for p in skip}
    check("有真脚本的同名 stub 被标记跳过", "ActivationSequenceModule.cs" in names)
    check("没有真脚本的 stub 不被跳过", "OnlyStub.cs" not in names)
    check("识别 Dummy 特征", ka.is_asset_ripper_stub(
        dirty / "Assets/Scripts/Assembly-CSharp/SFS/Parts/Modules/ActivationSequenceModule.cs"))
    check("真脚本不误判为 stub",
          not ka.is_asset_ripper_stub(dirty / "Assets/Scripts/Parts/Utility/ActivationSequenceModule.cs"))
    dups = ka.find_duplicate_types(dirty / "Assets" / "Scripts")
    check("Toolkit 健康检查能报出重复类", "SFS.Parts.Modules.ActivationSequenceModule" in dups)
    check("健康检查不误报 OnlyStub", "SFS.Parts.Modules.OnlyStub" not in dups)

    print("\n=== 5. 嵌套类型不参与判重（防误删真脚本）===")
    nested = temp / "NestedToolkit"
    # 复刻真实情况：AdaptModule/DomeModule/MagnetModule 各自内部都有嵌套 class Point
    for cls, fname in (("AdaptModule", "AdaptModule"), ("DomeModule", "DomeModule"), ("MagnetModule", "MagnetModule")):
        write(
            nested / f"Assets/Scripts/Parts/Interaction/{fname}.cs",
            f"""using UnityEngine;

namespace SFS.Parts.Modules
{{
    public class {cls} : MonoBehaviour
    {{
        public string s = "brace {{ inside string }}";

        [Serializable]
        public class Point
        {{
            public float x;
        }}
    }}
}}
""",
            "1" * 32,
        )
    n_dups = ka.find_duplicate_types(nested / "Assets" / "Scripts")
    check("嵌套同名类不算重复", not n_dups)
    n_removed, n_conf = ka.dedupe_conflicting_scripts(
        nested, nested, set(), lambda _m: None
    )
    check("嵌套场景零删除", n_removed == 0 and not n_conf)
    check("三个真脚本都还在", all(
        (nested / f"Assets/Scripts/Parts/Interaction/{f}.cs").is_file()
        for f in ("AdaptModule", "DomeModule", "MagnetModule")
    ))
    check("字符串里的花括号不影响深度统计",
          ka.declared_types(nested / "Assets/Scripts/Parts/Interaction/AdaptModule.cs")
          == {("SFS.Parts.Modules.AdaptModule", False)})

    print(f"\n结果: {ok} 通过 {fail} 失败")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
