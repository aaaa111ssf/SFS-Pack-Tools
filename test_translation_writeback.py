"""汉化写回回归：只改显示字段，分类名/变量名这类标识符绝不改。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sfs_pack_tool_logic as L

PASS = 0
FAIL = 0


def check(name, ok, extra=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [OK ] {name}")
    else:
        FAIL += 1
        print(f"  [!! ] {name} {extra}")


def main():
    print("\n=== 1. 白名单判断 ===")
    check("PickCategory.m_Name 不可写", not L._writable_loc_path("PickCategory.m_Name"))
    check("saves[].name 不可写", not L._writable_loc_path("saves[0].name"))
    check("variableName 不可写", not L._writable_loc_path("parts[2].variableName"))
    check("displayName 可写", L._writable_loc_path("displayName"))
    check("列表里的 DisplayName 可写", L._writable_loc_path("elements[0].DisplayName"))
    check("Unit 可写", L._writable_loc_path("thrust.Unit"))
    check("未知字段不可写", not L._writable_loc_path("someRandomField"))
    check("TranslatableName + plainText=0 不可写",
          not L._writable_loc_path("TranslatableName", {"plainText": 0}))
    check("TranslatableName + plainText=1 可写",
          L._writable_loc_path("TranslatableName", {"plainText": 1}))

    print("\n=== 2. 同一句话出现在标识符里时只改显示字段 ===")
    text = "Artemis Gateway Station"
    trans = {text: "阿尔忒弥斯门户站"}
    tree = {
        "displayName": text,
        "Description": text,
        "m_Name": text,
        "PickCategory": {"m_Name": text},
        "variableName": text,
        "saves": [{"name": text, "DisplayName": text}],
        "TranslatableName": text,
        "plainText": 0,
    }
    changed, kept = L.apply_translation_to_tree(tree, trans)
    check("只改到 3 处显示字段", changed == 3, f"changed={changed}")
    check("displayName 已翻译", tree["displayName"] == "阿尔忒弥斯门户站")
    check("Description 已翻译", tree["Description"] == "阿尔忒弥斯门户站")
    check("列表里的 DisplayName 已翻译", tree["saves"][0]["DisplayName"] == "阿尔忒弥斯门户站")
    check("m_Name 保持原样", tree["m_Name"] == text)
    check("PickCategory.m_Name 保持原样", tree["PickCategory"]["m_Name"] == text)
    check("variableName 保持原样", tree["variableName"] == text)
    check("saves[].name 保持原样", tree["saves"][0]["name"] == text)
    check("TranslatableName(plainText=0) 保持原样", tree["TranslatableName"] == text)
    check("跳过的标识符数量为 5", kept == 5, f"kept={kept}")

    print("\n=== 3. plainText=1 的 TranslatableName 可以翻 ===")
    tree2 = {"TranslatableName": "Fuel", "plainText": 1}
    changed2, kept2 = L.apply_translation_to_tree(tree2, {"Fuel": "燃料"})
    check("改到 1 处", changed2 == 1 and tree2["TranslatableName"] == "燃料", f"changed={changed2}")

    print("\n=== 4. 官方翻译 key 不写回 ===")
    official = sorted(L.OFFICIAL_LOC_KEYS)[0]
    tree3 = {"displayName": official}
    changed3, _ = L.apply_translation_to_tree(tree3, {official: "不该写入"})
    check("官方 key 保持原样", changed3 == 0 and tree3["displayName"] == official)

    print("\n=== 5. Author 先翻译再追加，重复执行不叠加 ===")
    tree4 = {"Author": "旧作者"}
    L.apply_translation_to_tree(tree4, {"旧作者": "新作者"}, author=" by A")
    check("Author 已翻译并追加", tree4["Author"] == "新作者 by A", tree4["Author"])
    L.apply_translation_to_tree(tree4, {"旧作者": "新作者"}, author=" by A")
    check("再跑一次不重复追加", tree4["Author"].count("by A") == 1, tree4["Author"])

    print(f"\n{'ALL PASS' if FAIL == 0 else 'FAILED'}  (pass={PASS} fail={FAIL})")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
