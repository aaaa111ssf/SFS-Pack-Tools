import base64
import json
import UnityPy
import os
import re
import tempfile
import argparse

INPUT_FILE = "mod.pack"
EXTRACTED_FILE = "texts_to_translate.json"
TRANSLATED_FILE = "texts_to_translated_zh.json"
OUTPUT_FILE = "mod_CN.pack"

AUTHOR_SUFFIX = "〈A Future star汉化〉"

_interactive = True

SAFE_FIELDS = {'displayName', 'description', 'label', 'DisplayName', 
               'Description', 'Author', 'TranslatableName'}

DANGER_PATH_KEYWORDS = {
    'variableName', 'variable', 'm_Name', 'input', 'output', 'name', 
    'id', 'type', 'key', 'reference', 'tag', 'layer', 'fragmentName',
    'saves', 'points', 'elements'
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
    'editing', 'wide', 'basic', 'eight', 'six', 'ten', 'twelve',
    'transparent', 'background', 'rendering', 'queue',
    'deploy', 'parachute', 'expanded', 'panel',
    'door', 'wheel', 'ring', 'bay', 'interstage',
    'inverted', 'collision', 'efficiency', 'wake',
    'directional', 'vector', 'velocity', 'scaling', 'offset',
    'slider', 'adjust', 'click', 'this', 'with', 'without',
    'like', 'will', 'form', 'frost', 'cryogenic', 'surface',
    'fully', 'fueled', 'starship', 'toggle', 'spawn', 'split',
    'fire', 'detach', 'separation', 'capsule', 'array', 'arrows',
    'faced', 'flat', 'folds', 'foot', 'leg', 'metal', 'rivets',
    'white', 'black', 'blue', 'green', 'orange', 'purple', 'gray',
    'pattern', 'torque', 'export', 'import', 'base', 'basic',
    'generate', 'landing', 'ball', 'capsule',
    'kn', 'kl', 'ml', 'mms', 'v0', 'v1', 'v2', 'v3', 'v4', 'v5',
    'water', 'oxygen', 'food', 'health', 'sanity', 'power',
    'circle', 'hinge', 'piston', 'robotics', 'life', 'support',
    'crew', 'greenhouse', 'electrolysis', 'recycler',
    'rotation', 'offset', 'scale',
}


def is_display_text_extract(s):
    if not s or len(s) < 2:
        return False
    
    if re.match(r'^[0-9\s\.\,\%\+\-\*\/\(\)]+$', s):
        return False
    
    if 'UnityEngine' in s or 'Assembly-' in s or 'SFS.' in s:
        return False
    
    if '/' in s or '\\' in s or s.startswith('.'):
        return False
    
    if '+' in s:
        return False
    
    if '*' in s:
        return False
    
    if '/' in s:
        if not re.search(r'[A-Za-z]/[A-Za-z]', s):
            return False
    
    if '-' in s:
        if re.search(r'\d\s*-\s*\d', s) or re.search(r'[a-z_]\s*-\s*\d', s):
            return False
    
    if '.' in s and not s.startswith('.'):
        return True
    
    if s[0].isupper():
        return True
    
    if any(c.isupper() for c in s[1:]):
        return True
    
    if ' ' in s:
        return True
    
    if any('\u4e00' <= c <= '\u9fff' for c in s):
        return True
    
    if re.match(r'^[a-z]+$', s) and len(s) <= 20:
        if s.lower() in COMMON_WORDS:
            return True
    
    if re.match(r'^[a-z_][a-z0-9_]*$', s):
        words = s.split('_')
        common_count = sum(1 for w in words if w.lower() in COMMON_WORDS)
        if common_count >= len(words) * 0.5:
            return True
        return False
    
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
        if _interactive:
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
                        if is_display_text_extract(value):
                            all_texts.add(value)
                    
                    recursive_walk(tree, '', collect)
                
                elif obj.type.name == "TextAsset":
                    data_text = obj.read()
                    if hasattr(data_text, 'text') and data_text.text:
                        for line in data_text.text.split('\n'):
                            line = line.strip()
                            if is_display_text_extract(line):
                                all_texts.add(line)
            except:
                continue
        
        print(f"    当前累计 {len(all_texts)} 条")
    
    output_dict = {text: text for text in sorted(list(all_texts))}
    with open(EXTRACTED_FILE, 'w', encoding='utf-8') as f:
        json.dump(output_dict, f, ensure_ascii=False, indent=2)
    
    print(f"\n提取完成！共 {len(output_dict)} 条文本 -> {EXTRACTED_FILE}")
    if _interactive:
        input("\n按回车键返回菜单...")


def is_path_safe(path):
    is_safe = any(sf in path for sf in SAFE_FIELDS)
    is_danger = any(dk in path for dk in DANGER_PATH_KEYWORDS) and not is_safe
    return not is_danger


def write():
    print("\n正在写入汉化...")
    
    if not os.path.exists(INPUT_FILE):
        print(f"错误: 找不到 {INPUT_FILE}")
        if _interactive:
            input("\n按回车键返回...")
        return
    if not os.path.exists(TRANSLATED_FILE):
        print(f"错误: 找不到 {TRANSLATED_FILE}")
        if _interactive:
            input("\n按回车键返回...")
        return
    
    with open(INPUT_FILE, 'r', encoding='utf-8-sig') as f:
        data = json.load(f)
    with open(TRANSLATED_FILE, 'r', encoding='utf-8') as f:
        translations = json.load(f)
    
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
                        with open(os.path.join(tmpdir, saved_files[0]), 'rb') as f_bundle:
                            updated_binary = f_bundle.read()
                        data[build_key] = base64.b64encode(updated_binary).decode('utf-8')
                        print(f"    保存成功 ({len(updated_binary)} 字节)")
                    else:
                        raise Exception("临时目录为空")
            except:
                try:
                    updated_binary = env.file.save(packer='lzma')
                    data[build_key] = base64.b64encode(updated_binary).decode('utf-8')
                    print(f"    回退保存成功")
                except Exception as e:
                    print(f"    保存失败: {e}")
        else:
            print(f"    未找到可修改的文本")
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    
    print(f"\n写入完成！ -> {OUTPUT_FILE}")
    if _interactive:
        input("\n按回车键返回菜单...")


def main():
    global INPUT_FILE, TRANSLATED_FILE, OUTPUT_FILE, EXTRACTED_FILE, AUTHOR_SUFFIX, _interactive
    
    parser = argparse.ArgumentParser(
        description='SFS Mod 汉化工具 by A Future star',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  python SFS_Mod_Toolv17.py extract                               
  python SFS_Mod_Toolv17.py write                                 
  python SFS_Mod_Toolv17.py -i mod.pack -t zh.json -o CN.pack write
  python SFS_Mod_Toolv17.py --auto                               
  python SFS_Mod_Toolv17.py -i mod.pack extract                
        '''
    )
    
    parser.add_argument('mode', nargs='?', default=None,
                        choices=['extract', 'write', '1', '2'],
                        help='操作模式: extract/1=提取文本, write/2=写入汉化')
    
    parser.add_argument('-i', '--input', default='mod.pack',
                        help='输入 .pack 文件 (默认: mod.pack)')
    parser.add_argument('-t', '--trans', default='texts_to_translated_zh.json',
                        help='翻译 JSON 文件 (默认: texts_to_translated_zh.json)')
    parser.add_argument('-o', '--output', default='mod_CN.pack',
                        help='输出 .pack 文件 (默认: mod_CN.pack)')
    parser.add_argument('-e', '--extracted', default='texts_to_translate.json',
                        help='提取出的文本文件 (默认: texts_to_translate.json)')
    
    parser.add_argument('--auto', action='store_true',
                        help='自动模式：先提取再写入（需要翻译文件已存在）')
    parser.add_argument('--author', default='〈A Future star汉化〉',
                        help='作者后缀 (默认: 〈A Future star汉化〉)')
    
    parser.add_argument('--menu', action='store_true',
                        help='强制显示交互菜单')
    
    args = parser.parse_args()
    
    INPUT_FILE = args.input
    TRANSLATED_FILE = args.trans
    OUTPUT_FILE = args.output
    EXTRACTED_FILE = args.extracted
    AUTHOR_SUFFIX = args.author
    
    # 命令行模式不需要等待按键
    if args.mode in ('extract', '1', 'write', '2') or args.auto:
        _interactive = False
    
    print("=" * 50)
    print("      SFS Mod 汉化工具 by A Future star")
    print("=" * 50)
    print(f"  输入: {INPUT_FILE}")
    print(f"  翻译: {TRANSLATED_FILE}")
    print(f"  输出: {OUTPUT_FILE}")
    print("=" * 50)
    
    if args.menu:
        interactive_menu()
        return
    
    if args.auto:
        print("\n🚀 自动模式：提取 → 写入")
        extract()
        if os.path.exists(TRANSLATED_FILE):
            write()
        else:
            print(f"\n⚠️  翻译文件 {TRANSLATED_FILE} 不存在，请先翻译再运行写入")
            print(f"   提取的文本已保存到 {EXTRACTED_FILE}")
        return
    
    if args.mode in ('extract', '1'):
        extract()
    elif args.mode in ('write', '2'):
        write()
    else:
        interactive_menu()


def interactive_menu():
    """交互式菜单模式"""
    while True:
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
    main()
