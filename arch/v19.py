import base64
import json
import UnityPy
import os
import re
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox

INPUT_FILE = ""
TRANSLATED_FILE = ""
OUTPUT_FILE = "mod_CN.pack"
EXTRACTED_FILE = "texts_to_translate.json"
DEFAULT_AUTHOR = "〈A Future star汉化〉"

#这里是黑名单
EXCLUDE_WORDS = [
    "Color_Gray", "Toggle", "width", "target_state", "tank", "height",
    "Flat_Shadow", "Color_White", "Admin", "Default", "Empty"
]
MATCH_MODE = "exact"

def safe(v, default):
    return v if v and isinstance(v, str) and v.strip() else default

def validate_input():
    if not INPUT_FILE:
        return "未选择 mod.pack"
    return None

def validate_full():
    if not INPUT_FILE:
        return "未选择 mod.pack"
    if not TRANSLATED_FILE:
        return "未选择翻译文件"
    return None

def is_exclude_word(text):
    text_clean = text.strip()
    if MATCH_MODE == "exact":
        return text_clean in EXCLUDE_WORDS
    elif MATCH_MODE == "ignore_case":
        text_lower = text_clean.lower()
        ban_lower = [w.lower() for w in EXCLUDE_WORDS]
        return text_lower in ban_lower
    elif MATCH_MODE == "contain":
        return any(ban_word in text_clean for ban_word in EXCLUDE_WORDS)
    return False

def run_async(func, log):
    def wrapper():
        try:
            func(log)
        except Exception as e:
            log(f"❌ 线程崩溃: {e}")
    t = threading.Thread(target=wrapper, daemon=True)
    t.start()

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

QIAN_DANGER_PATH_KEYWORDS = {
    'm_MethodName', 'm_ClassName', 'm_Namespace', 'm_TypeName',
    'variableName', 'input', 'output', 'name', 'id', 'type', 'key',
    'reference', 'tag', 'layer', 'fragmentName', 'saves', 'points',
    'elements', 'm_Name', 'm_Script'
}

QIAN_COMMON_WORDS = {
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

def qian_is_path_safe(path):
    for dk in QIAN_DANGER_PATH_KEYWORDS:
        if dk in path:
            return False
    return True

def qian_is_code_identifier(s):
    if s.islower() and ' ' not in s and s not in QIAN_COMMON_WORDS:
        return True
    if '_' in s and ' ' not in s:
        parts = s.split('_')
        all_common = all(p.lower() in QIAN_COMMON_WORDS for p in parts if p)
        if all_common:
            return False
        return True
    if ' ' not in s and re.match(r'^[A-Za-z][A-Za-z0-9_]*$', s):
        if s.isupper() or s.islower():
            return False
        if s in QIAN_COMMON_WORDS:
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

def qian_is_display_text_extract(s):
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
    if qian_is_code_identifier(s):
        return False
    if any('\u4e00' <= c <= '\u9fff' for c in s):
        return True
    if s[0].isupper() and ' ' in s:
        return True
    if s in QIAN_COMMON_WORDS:
        return True
    return False

def shallow_extract(log):
    err = validate_input()
    if err:
        log(f"❌ {err}")
        return
    log("📤 开始浅层提取（qian.py 逻辑）...")
    try:
        with open(INPUT_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception as e:
        log(f"❌ JSON读取错误: {e}")
        return
    all_texts = set()
    build_keys = ['AndroidBuild', 'WindowsBuild', 'MacBuild', 'IOS_Build']
    for build_key in build_keys:
        if build_key not in data or not data[build_key]:
            continue
        log(f"  扫描 {build_key}...")
        try:
            binary_data = base64.b64decode(data[build_key])
            env = UnityPy.load(binary_data)
        except Exception as e:
            log(f"❌ {build_key} 解包失败: {e}")
            continue
        for obj in env.objects:
            try:
                if obj.type.name == "MonoBehaviour":
                    tree = obj.read_typetree()
                    if tree is None:
                        continue
                    def collect(parent, key, value, path):
                        if qian_is_path_safe(path) and qian_is_display_text_extract(value) and not is_exclude_word(value):
                            all_texts.add(value)
                    recursive_walk(tree, '', collect)
            except Exception as e:
                log(f"⚠️ 对象处理异常: {e}")
                continue
    output_dict = {text: text for text in sorted(list(all_texts))}
    with open(EXTRACTED_FILE, 'w', encoding='utf-8') as f:
        json.dump(output_dict, f, ensure_ascii=False, indent=2)
    log(f"✅ 浅层提取完成！共 {len(output_dict)} 条文本 → {EXTRACTED_FILE}")

V18_SAFE_FIELDS = {'displayName', 'description', 'label', 'DisplayName', 
                   'Description', 'Author', 'TranslatableName'}

V18_DANGER_PATH_KEYWORDS = {
    'variableName', 'variable', 'm_Name', 'input', 'output', 'name', 
    'id', 'type', 'key', 'reference', 'tag', 'layer', 'fragmentName',
    'saves', 'points', 'elements'
}

V18_COMMON_WORDS = {
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
    'slider', 'adjust', 'click', 'frost', 'cryogenic', 'surface',
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

def v18_is_display_text_extract(s):
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
        if s.lower() in V18_COMMON_WORDS:
            return True
    if re.match(r'^[a-z_][a-z0-9_]*$', s):
        words = s.split('_')
        common_count = sum(1 for w in words if w.lower() in V18_COMMON_WORDS)
        if common_count >= len(words) * 0.5:
            return True
        return False
    return False

def v18_is_path_safe(path):
    is_safe = any(sf in path for sf in V18_SAFE_FIELDS)
    is_danger = any(dk in path for dk in V18_DANGER_PATH_KEYWORDS) and not is_safe
    return not is_danger

def deep_extract(log):
    err = validate_input()
    if err:
        log(f"❌ {err}")
        return
    log("📤 开始深层提取（v18.py 逻辑）...")
    try:
        with open(INPUT_FILE, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception as e:
        log(f"❌ JSON读取错误: {e}")
        return
    all_texts = set()
    build_keys = ['AndroidBuild', 'WindowsBuild', 'MacBuild', 'IOS_Build']
    for build_key in build_keys:
        if build_key not in data or not data[build_key]:
            continue
        log(f"  扫描 {build_key}...")
        try:
            binary_data = base64.b64decode(data[build_key])
            env = UnityPy.load(binary_data)
        except Exception as e:
            log(f"❌ {build_key} 解包失败: {e}")
            continue
        for obj in env.objects:
            try:
                if obj.type.name == "MonoBehaviour":
                    tree = obj.read_typetree()
                    if tree is None:
                        continue
                    def collect(parent, key, value, path):
                        if v18_is_display_text_extract(value) and not is_exclude_word(value):
                            all_texts.add(value)
                    recursive_walk(tree, '', collect)
                elif obj.type.name == "TextAsset":
                    data_text = obj.read()
                    if hasattr(data_text, 'text') and data_text.text:
                        for line in data_text.text.split('\n'):
                            line = line.strip()
                            if v18_is_display_text_extract(line) and not is_exclude_word(line):
                                all_texts.add(line)
            except Exception as e:
                log(f"⚠️ 对象处理异常: {e}")
                continue
        log(f"    当前累计 {len(all_texts)} 条")
    output_dict = {text: text for text in sorted(list(all_texts))}
    with open(EXTRACTED_FILE, 'w', encoding='utf-8') as f:
        json.dump(output_dict, f, ensure_ascii=False, indent=2)
    log(f"✅ 深层提取完成！共 {len(output_dict)} 条文本 → {EXTRACTED_FILE}")

def write(log, author_text):
    global OUTPUT_FILE
    OUTPUT_FILE = safe(OUTPUT_FILE,"mod_CN.pack")
    err = validate_full()
    if err:
        log(f"❌ {err}")
        return
    try:
        with open(INPUT_FILE,"r",encoding="utf-8-sig") as f:
            data=json.load(f)
        with open(TRANSLATED_FILE,"r",encoding="utf-8") as f:
            trans=json.load(f)
    except Exception as e:
        log(f"❌ 文件读取失败: {e}")
        return
    trans={k:v for k,v in trans.items() if k!=v}
    for key in ["AndroidBuild","WindowsBuild","MacBuild","IOS_Build"]:
        if key not in data:
            continue
        log(f"处理 {key}")
        try:
            env=UnityPy.load(base64.b64decode(data[key]))
        except Exception as e:
            log(f"❌ 解包失败: {e}")
            continue
        changed=0
        for obj in env.objects:
            if obj.type.name!="MonoBehaviour":
                continue
            try:
                tree=obj.read_typetree()
                if not tree:
                    continue
                def rep(node):
                    nonlocal changed
                    if isinstance(node,dict):
                        for k,v in list(node.items()):
                            if isinstance(v,str):
                                if classify_code(v):
                                    continue
                                if k=="Author":
                                    node[k]=v+author_text
                                    changed+=1
                                elif v in trans:
                                    node[k]=trans[v]
                                    changed+=1
                            elif isinstance(v,(dict,list)):
                                rep(v)
                    elif isinstance(node,list):
                        for i,v in enumerate(node):
                            if isinstance(v,str):
                                if not classify_code(v) and v in trans:
                                    node[i]=trans[v]
                                    changed+=1
                            else:
                                rep(v)
                rep(tree)
                obj.save_typetree(tree)
            except Exception as e:
                log(f"⚠️ 对象错误: {e}")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                env.save(pack="lzma",out_path=tmp)
                file=os.listdir(tmp)[0]
                with open(os.path.join(tmp,file),"rb") as f:
                    data[key]=base64.b64encode(f.read()).decode()
            log(f"✔ {key}完成")
        except Exception as e:
            log(f"❌ 保存失败: {e}")
    try:
        with open(OUTPUT_FILE,"w",encoding="utf-8") as f:
            json.dump(data,f,ensure_ascii=False)
        log(f"✔ 输出成功：{OUTPUT_FILE}")
    except Exception as e:
        log(f"❌ 输出失败: {e}")

def classify_code(s):
    if not isinstance(s, str):
        return False
    if s.strip() == "":
        return True
    if re.match(r'^-?\d+(\.\d+)?$', s.strip()):
        return True
    if re.match(r'^[A-Za-z][A-Za-z0-9_]*$', s):
        if any(c.isupper() for c in s[1:]) and "_" not in s:
            return True
    if s.startswith(("Toggle","Deploy","Hide","Spawn","Fire","Generate","Start","Set","Get")):
        return True
    if "/" in s or "\\" in s:
        return True
    return False

class App:
    def __init__(self,root):
        self.root=root
        root.title("SFS Pack Toolsv20 by A Future star")
        root.geometry("800x600")
        
        self.author_var = tk.StringVar(value=DEFAULT_AUTHOR)
        
        tk.Button(root,text="选择mod.pack",command=self.pick_input, font=("微软雅黑",10)).pack(pady=3)
        tk.Button(root,text="选择翻译文件",command=self.pick_trans, font=("微软雅黑",10)).pack(pady=3)
        
        tk.Label(root, text="汉化模组作者：", font=("微软雅黑",10)).pack(pady=2)
        author_entry = tk.Entry(root, textvariable=self.author_var, font=("微软雅黑",10))
        author_entry.pack(pady=2, fill="x", padx=50)
        
        tk.Button(root,text="浅层提取 (qian.py)",command=self.run_shallow_extract, 
                  font=("微软雅黑",10), bg="#e6f7ff").pack(pady=3, fill="x", padx=50)
        tk.Button(root,text="深层提取 (v18.py)",command=self.run_deep_extract, 
                  font=("微软雅黑",10), bg="#fff2e6").pack(pady=3, fill="x", padx=50)
        
        tk.Button(root,text="写入汉化",command=self.run_write, font=("微软雅黑",10)).pack(pady=3)
        tk.Button(root,text="一键处理",command=self.run_auto, font=("微软雅黑",10)).pack(pady=3)
        
        self.log=scrolledtext.ScrolledText(root, font=("Consolas",9))
        self.log.pack(fill="both",expand=True,padx=5,pady=5)

    def log_print(self,msg):
        self.log.insert(tk.END,msg+"\n")
        self.log.see(tk.END)
        self.root.update()

    def pick_input(self):
        global INPUT_FILE
        INPUT_FILE=filedialog.askopenfilename(
            filetypes=[("Pack文件","*.pack"),("所有文件","*.*")]
        )
        self.log_print(f"已选择源文件：{INPUT_FILE}")

    def pick_trans(self):
        global TRANSLATED_FILE
        TRANSLATED_FILE=filedialog.askopenfilename(
            filetypes=[("JSON文件","*.json"),("所有文件","*.*")]
        )
        self.log_print(f"已选择翻译文件：{TRANSLATED_FILE}")

    def run_shallow_extract(self):
        run_async(shallow_extract,self.log_print)

    def run_deep_extract(self):
        run_async(deep_extract,self.log_print)

    def run_write(self):
        author_text = self.author_var.get()
        def task(log):
            write(log, author_text)
        run_async(task, self.log_print)

    def run_auto(self):
        author_text = self.author_var.get()
        def run():
            err = validate_full()
            if err:
                self.log_print(f"❌ {err}")
                return
            self.log_print("一键模式：深层提取 → 写入汉化")
            deep_extract(self.log_print)
            if os.path.exists(TRANSLATED_FILE):
                write(self.log_print, author_text)
        run_async(run,self.log_print)

if __name__=="__main__":
    root=tk.Tk()
    App(root)
    root.mainloop()