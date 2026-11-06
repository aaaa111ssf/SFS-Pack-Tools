import base64
import json
import UnityPy
import os
import re
import tempfile

INPUT_FILE = "mod.pack"
EXTRACTED_FILE = "texts_to_translate.json"
TRANSLATED_FILE = "texts_to_translated_zh.json"
OUTPUT_FILE = "mod_CN.pack"

AUTHOR_SUFFIX = "〈A Future star汉化〉"

SAFE_FIELDS = {'displayName', 'DisplayName', 'Description', 'description',
               'label', 'Author', 'TranslatableName'}

DANGER_PATH_KEYWORDS = {
    'm_MethodName', 'm_ClassName', 'm_Namespace', 'm_TypeName',
    'variableName', 'input', 'output', 'name', 'id', 'type', 'key',
    'reference', 'tag', 'layer', 'fragmentName', 'saves', 'points',
    'elements', 'm_Name', 'm_Script'
}

COMMON_WORDS = {
    'module', 'part', 'engine', 'fuel', 'tank', 'size', 'layer',
    'hide', 'show', 'width', 'height', 'length', 'mode', 'style',
    'switch', 'position', 'smooth', 'angle', 'bevel', 'edge',
    'booster', 'nozzle', 'flame', 'color', 'mass', 'lift', 'wing',
    'wheel', 'solar', 'panel', 'separator', 'docking', 'parachute',
    'aero', 'dome', 'cone', 'fairing', 'ring', 'strut', 'pipe',
    'utility', 'structural', 'procedural', 'actual', 'bottom',
    'top', 'left', 'right', 'center', 'expanded', 'deployed',
    'thrust', 'torque', 'plume', 'animation', 'target',
    'attachment', 'astronaut', 'buoyancy', 'cargo', 'centroid',
    'modifier', 'connection', 'cutting', 'demonstration', 'sample',
    'handheld', 'thermal', 'frontier', 'hawk', 'titan', 'valiant',
    'kolibri', 'kuiper', 'ion', 'probe', 'rover', 'landing',
    'heat', 'shield', 'support', 'main', 'hollow', 'curve',
    'editing', 'wide', 'basic', 'transparent', 'background',
    'rendering', 'queue', 'deploy', 'panel', 'expanded',
    'door', 'wheel', 'ring', 'bay', 'interstage',
    'inverted', 'collision', 'efficiency', 'wake',
    'directional', 'vector', 'velocity', 'scaling', 'offset',
    'slider', 'adjust', 'click', 'frost', 'cryogenic', 'surface',
    'fully', 'fueled', 'starship', 'toggle', 'spawn', 'split',
    'fire', 'detach', 'separation', 'capsule', 'array', 'arrows',
    'faced', 'flat', 'folds', 'foot', 'leg', 'rivets',
    'pattern', 'export', 'import', 'base', 'generate', 'ball',
    'rotation', 'scale', 'variable', 'kn', 'srb', 'sound',
    'flat', 'smooth', 'faces', 'thin', 'panle', 'rad', 'line',
    'point', 'shape', 'side', 'opaque', 'red', 'blue', 'green',
    'yellow', 'pink', 'orange', 'purple', 'brown', 'white', 'black',
    'gray', 'dark', 'light', 'vacuum', 'sea', 'level', 'exhaust',
    'flame', 'glow', 'smoke', 'sparks', 'burn', 'stripes',
    'legs', 'perpendicular', 'piston', 'magnetic', 'movement',
    'collider', 'collision', 'attachment', 'surface',
    'detach', 'check', 'flat', 'front', 'back', 'pod',
    'tank', 'enclosure', 'core', 'pipe', 'plate',
    'capsule', 'probe', 'procedural', 'heat', 'shield',
    'separation', 'separator', 'motor',
    'ToggleEngine', 'ToggleRCS', 'DeployParachute', 'GenerateMesh',
    'HideEngine', 'HideFlame', 'HideGlow', 'HideSound',
    'HideParts', 'HidePart', 'HideInterface', 'HideStrut',
    'HideCollision', 'HideEdge', 'HideBase', 'HideShell',
    'HideWheel', 'HideWhite',
    'Detach', 'Split', 'Spawn', 'Fire', 'Toggle',
    'Low', 'Medium', 'High', 'Ultra',
    'None', 'Basic',
    'Interstage', 'InterstageFull',
    'Heat_Shield_Name', 'Panel_Expanded', 'Landing_Leg_Expanded',
    'Style_Switch', 'Cutting_Mode_Switch', 'Drag_Collider_Switch',
    'Start_Cutting', 'Flame_Edite_Mode', 'Particle_Editing_Mode',
    'Astronaut_Mode', 'Surface_Show',
    'Only_Keep_Door', 'Side_Parachute',
    'Transparent_background',
    '6 wide', '8 wide', '10 wide', '12 wide',
    'Six_Wide_Parts', 'Eight_Wide_Parts',
    'Ten_Wide_Parts', 'Twelve_Wide_Parts',
    'Basic_Parts',
}


def is_path_safe(path):
    for dk in DANGER_PATH_KEYWORDS:
        if dk in path:
            return False
    return True


def is_code_identifier(s):
    if s.islower() and ' ' not in s and s not in COMMON_WORDS:
        return True

    if '_' in s and ' ' not in s:
        parts = s.split('_')
        all_common = all(p.lower() in COMMON_WORDS for p in parts if p)
        if all_common:
            return False
        return True

    if ' ' not in s and re.match(r'^[A-Za-z][A-Za-z0-9_]*$', s):
        if s.isupper() or s.islower():
            return False
        if s in COMMON_WORDS:
            return False
        method_prefixes = ('Toggle', 'Generate', 'Hide', 'Detach', 'Split',
                          'Spawn', 'Fire', 'Deploy', 'Start', 'Cut',
                          'Get', 'Set', 'Create', 'Destroy', 'Update',
                          'Enable', 'Disable')
        for prefix in method_prefixes:
            if s.startswith(prefix) and len(s) > len(prefix):
                return True
        if s.endswith('Module') and len(s) > 6:
            return True
        if re.search(r'[a-z][A-Z]', s):
            return True
        return False

    return False


def is_display_text_extract(s):
    if not s or len(s) < 2:
        return False

    if re.match(r'^[0-9\s\.\,\%\+\-\*\/\(\)]+$', s):
        return False

    if 'UnityEngine' in s or 'Assembly-' in s or 'SFS.' in s:
        return False

    if '/' in s or '\\' in s:
        return False

    if any(op in s for op in ['*', '/', '=']):
        return False
    if '+' in s or '-' in s:
        if re.search(r'\d\s*[\+\-]', s) or re.search(r'[\+\-]\s*\d', s):
            return False
        if '_' in s:
            return False

    if '(' in s or ')' in s:
        return False

    if is_code_identifier(s):
        return False

    if any('\u4e00' <= c <= '\u9fff' for c in s):
        return True

    if s[0].isupper() and ' ' in s:
        return True

    if s in COMMON_WORDS:
        return True

    return False


def recursive_walk(node, path='', callback=None):
    if isinstance(node, dict):
        for k, v in node.items():
            child_path = f"{path}.{k}" if path else k
            if isinstance(v, str):
                callback(node, k, v, child_path)
            elif isinstance(v, (dict, list)):
                recursive_walk(v, child_path, callback)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            child_path = f"{path}[{i}]"
            if isinstance(v, str):
                callback(node, i, v, child_path)
            elif isinstance(v, (dict, list)):
                recursive_walk(v, child_path, callback)


def extract():
    print("\n正在提取文本...")
    if not os.path.exists(INPUT_FILE):
        print(f"错误: 找不到文件 {INPUT_FILE}")
        input("\n按回车键返回...")
        return

    with open(INPUT_FILE, 'r', encoding='utf-8-sig') as f:
        data = json.load(f)

    all_texts = set()

    for build_key in ['AndroidBuild', 'WindowsBuild', 'MacBuild', 'IOS_Build']:
        if build_key not in data or not data[build_key]:
            continue

        print(f"  扫描 {build_key}...")
        binary_data = base64.b64decode(data[build_key])
        env = UnityPy.load(binary_data)

        for obj in env.objects:
            try:
                if obj.type.name == "MonoBehaviour":
                    tree = obj.read_typetree()
                    if tree is None:
                        continue

                    def collect(parent, key, value, path):
                        if not is_path_safe(path):
                            return
                        if is_display_text_extract(value):
                            all_texts.add(value)

                    recursive_walk(tree, '', collect)

            except:
                continue

    output_dict = {text: text for text in sorted(list(all_texts))}
    with open(EXTRACTED_FILE, 'w', encoding='utf-8') as f:
        json.dump(output_dict, f, ensure_ascii=False, indent=2)

    print(f"\n提取完成！共 {len(output_dict)} 条文本 -> {EXTRACTED_FILE}")
    input("\n按回车键返回菜单...")


def write():
    print("\n正在写入汉化...")

    if not os.path.exists(INPUT_FILE):
        print(f"错误: 找不到 {INPUT_FILE}")
        input("\n按回车键返回...")
        return
    if not os.path.exists(TRANSLATED_FILE):
        print(f"错误: 找不到 {TRANSLATED_FILE}")
        input("\n按回车键返回...")
        return

    with open(INPUT_FILE, 'r', encoding='utf-8-sig') as f:
        data = json.load(f)

    with open(TRANSLATED_FILE, 'r', encoding='utf-8') as f:
        translations = json.load(f)

    # 只替换真正发生翻译的内容
    active_translations = {k: v for k, v in translations.items() if k != v}
    print(f"    共 {len(active_translations)} 条需要替换")

    for build_key in ['AndroidBuild', 'WindowsBuild', 'MacBuild', 'IOS_Build']:
        if build_key not in data or not data[build_key]:
            continue

        print(f"\n  处理 {build_key}...")
        binary_data = base64.b64decode(data[build_key])
        env = UnityPy.load(binary_data)
        modified_count = 0

        for obj in env.objects:
            if obj.type.name != "MonoBehaviour":
                continue

            try:
                tree = obj.read_typetree()
                if tree is None:
                    continue

                modified = False

                def replace_node(node, path=""):
                    nonlocal modified

                    if isinstance(node, dict):
                        for k, v in list(node.items()):
                            child_path = f"{path}.{k}" if path else k

                            # 作者标记
                            if k == 'Author' and isinstance(v, str):
                                if AUTHOR_SUFFIX not in v:
                                    node[k] = v + AUTHOR_SUFFIX
                                    modified = True

                            elif isinstance(v, str):
                                if is_path_safe(child_path) and v in active_translations:
                                    node[k] = active_translations[v]
                                    modified = True

                            elif isinstance(v, (dict, list)):
                                replace_node(v, child_path)

                    elif isinstance(node, list):
                        for i, v in enumerate(node):
                            child_path = f"{path}[{i}]"

                            if isinstance(v, str):
                                if is_path_safe(child_path) and v in active_translations:
                                    node[i] = active_translations[v]
                                    modified = True

                            elif isinstance(v, (dict, list)):
                                replace_node(v, child_path)

                replace_node(tree)

                if modified:
                    obj.save_typetree(tree)
                    modified_count += 1

            except:
                continue

        if modified_count > 0:
            print(f"    修改了 {modified_count} 个对象")

            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    env.save(pack='lzma', out_path=tmpdir)

                    saved_files = os.listdir(tmpdir)
                    if saved_files:
                        with open(os.path.join(tmpdir, saved_files[0]), 'rb') as f:
                            updated_binary = f.read()

                        data[build_key] = base64.b64encode(updated_binary).decode('utf-8')
                        print(f"    保存成功 ({len(updated_binary)} 字节)")
                    else:
                        raise Exception("空输出目录")

            except Exception as e:
                # fallback
                try:
                    updated_binary = env.file.save(packer='lzma')
                    data[build_key] = base64.b64encode(updated_binary).decode('utf-8')
                    print("    回退保存成功")
                except Exception as e:
                    print(f"    保存失败: {e}")
        else:
            print("    未找到可修改文本")

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))

    print(f"\n写入完成！ -> {OUTPUT_FILE}")
    input("\n按回车键返回菜单...")


def show_menu():
    os.system('cls' if os.name == 'nt' else 'clear')
    print("=" * 50)
    print("      SFS Mod 汉化工具 by A Future star")
    print("=" * 50)
    print(f"  输入: {INPUT_FILE}")
    print(f"  翻译: {TRANSLATED_FILE}")
    print(f"  输出: {OUTPUT_FILE}")
    print("=" * 50)
    print("  1. 提取文本")
    print("  2. 写入汉化")
    print("  0. 退出")
    print("=" * 50)


def main():
    while True:
        show_menu()
        choice = input("请选择 (0-2): ").strip()
        if choice == '1':
            extract()
        elif choice == '2':
            write()
        elif choice == '0':
            print("再见！")
            break
        else:
            print("无效选择")
            input("按回车键继续...")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] in ("extract", "1"):
            extract()
        elif sys.argv[1] in ("write", "2"):
            write()
        else:
            main()
    else:
        main()
