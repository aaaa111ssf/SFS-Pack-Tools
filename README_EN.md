# SFS Pack Tool V2.3.6-PyQt
> **Localization writing, stripping, Prefab/texture export, and Unity project recovery**  
> Embedded AssetRipper 1.1.4 · Windows x64 · GPL-3.0-compliant distribution
>
> Language / 语言：[简体中文](README.md) · [English](README_EN.md) · [更新日志 / Changelog](CHANGELOG.md)

SFS Pack Tool processes SFS `.pack` mod files. It can extract translatable text, write translations into a new Pack, strip redundant platform builds to shrink file size, and export Unity AssetBundles as a Unity project containing real YAML Prefabs, textures, materials, and project configuration. The 2.3 series embeds the official AssetRipper 1.1.4 Windows x64 runtime, so no AssetRipper download, path selection, or setup is required. Unity-project export now merges new parts directly into the Modding Toolkit you specify.

Use this tool only with mods and assets that you own, are authorized to modify, or are otherwise legally allowed to process. For mods that depend on custom game assemblies, exported Prefabs and assets can be inspected and edited, but game-specific scripts may not compile in a blank Unity project.

| Item | Details |
| --- | --- |
| Supported system | Windows 64-bit |
| Main program | `SFS_Pack_Tool_v2.3.4_Embedded_GPL.exe` |
| Embedded exporter | AssetRipper 1.1.4 Windows x64 (forced built-in; no manual selection/download) |
| Interface languages | Chinese and English |
| License | GPL-3.0-or-later, with license text and corresponding source materials included |

## Features

The localization workflow reads the JSON container of an SFS `.pack` file and the Base64-encoded Unity AssetBundles inside it. It extracts displayable text for manual translation. When writing a translated Pack, it targets display-oriented fields such as `DisplayName`, `Description`, `TranslatableName`, and `Author`, while avoiding Unity object names, script references, and other high-risk serialized fields. Updated AssetBundles are saved with LZMA compression to preserve mod compatibility as far as possible.

| Feature | Result |
| --- | --- |
| Extract translatable text | Creates an editable JSON translation table at a user-selected location |
| Write localization and create Pack | Creates `original-name-CN.pack` beside the source Pack without overwriting it |
| Strip / minimize tool | Keeps only the target platform Build and CodeAssembly, removes the others, and greatly shrinks the `.pack` |
| Package info analysis | Shows pack size, CodeAssembly size, and per-platform “extracted size + part count” overview |
| Export a Unity project | Exports Prefabs, textures, materials, shaders, audio, and `.meta` files, and **merges them directly into the Modding Toolkit** |
| Embedded AssetRipper | Always uses the bundled 1.1.4; no manual path selection |
| Keep-alive import | Rewrites script GUID references against the Toolkit's scripts so components do not hang |
| Safe output handling | Adds only parts the Toolkit does not have; existing parts are skipped; never clears, deletes, or overwrites |
| Bilingual interface | Switch Chinese/English in the upper-right corner; the selection is saved automatically |

## Download and launch

Download the EXE from the release package and place it in a normal folder where you have write permission, for example `D:\Tools\SFS Pack Tool\`. Start it by double-clicking `SFS_Pack_Tool_v2.3.4_Embedded_GPL.exe`.

The EXE is signed with an AFuturestar self-signed certificate. Windows may still show an unknown publisher or SmartScreen warning on systems where that certificate has not been installed as a trusted publisher. Verify the public certificate and SHA-256 signature information provided in the release package before deciding whether to run it.

The embedded AssetRipper ships with the program, so nothing needs to be downloaded. On the first Unity project export, the embedded AssetRipper files are extracted to an `AssetRipper-1.1.4` folder next to the EXE. If that folder is not writable, the tool uses the current user's local application-data folder instead. This process only creates or completes files belonging to the tool; it does not delete existing user files.

| File or location | Purpose |
| --- | --- |
| `SFS_Pack_Tool_v2.3.4_Embedded_GPL.exe` | Main program with the embedded runtime |
| `AssetRipper-1.1.4/` | Embedded AssetRipper files extracted on first export |
| `%LOCALAPPDATA%\AFuturestar\SFS-Pack-Tool\` | Fallback extraction location when the EXE folder is not writable |
| `settings.json` | Stores language, author signature, and path preferences |
| `LICENSE-GPL-3.0.txt` | Full [GNU GPL v3][2] license text |
| `GPL_COMPLIANCE.md` | AssetRipper version, checksums, upstream link, and compliance information |

## Quick start

### 1. Select a Pack file
Click **Select source mod.pack** in the **Input Files** section and select the `.pack` file to process. The log shows the selected source file.

### 2. Extract translatable text
Optionally click **Choose save location** in the **Localization** section to choose the path and filename for the translation JSON, then click **Extract translatable text**. If no custom location is set, the default filename is `texts_to_translate.json`.

The generated file uses an `original text: translated text` structure. Edit only the value on the right.

```json
{
  "Engine": "Engine",
  "Fuel Tank": "Fuel Tank"
}
```

Keep the JSON valid: keys and values require double quotes, entries require commas between them, and the final entry must not end with a comma.

### 3. Apply translation and create a new Pack
After editing the JSON, click **Select translation JSON** in the **Input Files** section and choose the translated file. You may change the **Translator signature** if needed; the default is `〈A Future star汉化〉`. Then click **Apply translation and create Pack**. The tool creates `original-name-CN.pack` next to the original `.pack`; the original is never overwritten.

### 4. Export and merge into the Modding Toolkit
In the **Unity Prefab / Texture / Project Export** section, click **Select Toolkit** and choose the official Modding Toolkit project root (the folder containing `Assets\Scripts`), then click **Export Unity project**.

Parts are exported and merged directly into that Toolkit: only parts the Toolkit does not already have are added, and existing parts are skipped automatically. Export is staged in a temporary directory first, then the new parts are written into the Toolkit's `Assets`. Script references are rewritten to match the Toolkit's actual scripts so components do not hang after import. After it finishes, open `Assets/Resources/Parts` in the Toolkit to view and edit the new parts.

- If the tool reports “Modding Toolkit path is invalid”: the directory you chose does not contain `.cs.meta` scripts under `Assets\Scripts`. Select the official Toolkit project root instead.
- Exporting without a Toolkit path raises an error; you do not need a Toolkit path for localization only.

### 5. Strip / minimize (optional)
In the **Strip / minimize tool** section, first click **Package info** to review each platform's size and part count. Then choose a **Target platform** and an optional **Output location**, and click **Strip to target platform**. The tool keeps only the target platform Build and CodeAssembly, removes the others, and writes a smaller new `.pack` (in the source folder as `original-name-platform.pack` if no output location is set).

## AssetRipper behavior

The 2.3 series always uses the AssetRipper 1.1.4 embedded with the program. There is no AssetRipper path field, no manual selection, and no network download. The tool starts AssetRipper 1.1.4 with only the options supported by that version — `--port` and `--launch-browser false` — and never passes options unrecognized by 1.1.4.

If the embedded version exits abnormally, the tool restarts it from the **same embedded executable** with compatibility parameters; it never downloads anything. If the EXE cannot be extracted or started, make sure the containing folder is writable, ensure security software has not quarantined `AssetRipper-1.1.4`, and keep the full log output for diagnosis.

## Exported files

Export results are written into the selected Modding Toolkit, with new parts placed under its `Assets/Resources/Parts`. `.meta` files contain Unity GUID metadata and are matched against the Toolkit's scripts; always copy them with their matching assets. Running localization only creates no export project.

| Output | Description |
| --- | --- |
| `Toolkit/Assets/Resources/Parts/**/*.prefab` | New parts merged into the Toolkit (real Unity YAML Prefabs) |
| Textures/materials/shaders in per-platform builds | Serialized assets released together with the parts |
| `*.cs.meta` | Unity GUID metadata, rewritten and aligned to the Toolkit's scripts |
| Localization output `original-name-CN.pack` | New translated Pack beside the source file |
| Strip output `original-name-platform.pack` | Trimmed Pack keeping only the target platform |

## Troubleshooting

### Will a selected folder or Pack file be deleted?
No. Export only writes new parts into the Toolkit's `Assets`; existing parts are skipped. It does not clear, delete, or overwrite existing Toolkit content, the input Pack, or localization output.

### Do Toolkit script changes affect export?
Export aligns part script references to the scripts actually present in the Toolkit. Use a Toolkit version compatible with the parts' source; if a needed script is missing, the corresponding `m_Script` reference may still not resolve.

### What does “Unable to read .pack JSON” mean?
Confirm that the selected file is an SFS JSON-format `.pack`, not a ZIP file, another game file, or a truncated download. You can open the beginning of the file in a text editor to verify that it is a JSON object. Re-download the original mod if it cannot be read correctly.

### I only want localization, not Unity-project export
Use only **Extract translatable text** and **Apply translation and create Pack**. This workflow needs neither AssetRipper nor the Modding Toolkit.

### Why do exported Prefabs show Missing Script?
This can be expected. Some mods depend on SFS game assemblies or custom `CodeAssembly` code that cannot be fully restored in a blank Unity project. Prefabs, textures, and most serialized fields remain available for viewing and editing. References that can be satisfied by the Toolkit's scripts are handled automatically by the 2.3-series keep-alive alignment.

### The embedded AssetRipper cannot be extracted or started
Ensure that the EXE folder is writable and that security software has not quarantined the EXE or the `AssetRipper-1.1.4` folder. Move the EXE to a new folder under Documents or Desktop and try again. After a crash, the tool restarts from the embedded version with compatibility parameters and does not download anything. Keep the complete log output when reporting an issue.

## License and source code

The embedded [AssetRipper][1] 1.1.4 runtime is licensed under the [GNU General Public License v3][2]. Accordingly, this embedded distribution is provided under GPL-3.0-or-later. The source-code package includes the complete AssetRipper 1.1.4 source ZIP, the official Windows x64 runtime ZIP, SFS Pack Tool source files, build materials, and the license text. See `GPL_COMPLIANCE.md` (included in the source-code package) for version details, SHA-256 checksums, and upstream information.

> This README is usage documentation and not legal advice. When distributing or modifying this embedded edition, keep the GPL license, third-party notices, and corresponding source materials together.

## References

[1]: https://github.com/AssetRipper/AssetRipper
[2]: https://www.gnu.org/licenses/gpl-3.0.html

---
**SFS Pack Tool V2.3.6-PyQt · A Future star**
