; SFS Pack Tool 安装脚本（NSIS 3.10）
; 用目录版产物做安装包：装一次，之后启动 1~2 秒（不用每次解压 118MB）

Unicode true

!include "MUI2.nsh"
!include "FileFunc.nsh"

!define APPNAME      "SFS Pack Tool"
!define APPVERSION   "2.3.6-PyQt"
!define SHORTNAME    "SFS Pack Tool"
!define PUBLISHER    "A Future star"
!define EXENAME      "SFS_Pack_Tool_v2.3.6-PyQt_portable.exe"
!define SOURCEDIR    "dist\SFS_Pack_Tool_v2.3.6-PyQt_portable"
!define REGKEY       "Software\AFuturestar\SFSPackTool"
!define UNINSTKEY    "Software\Microsoft\Windows\CurrentVersion\Uninstall\SFSPackTool"

Name "${APPNAME} ${APPVERSION}"
BrandingText "${APPNAME} ${APPVERSION} - ${PUBLISHER}"
OutFile "dist\SFS_Pack_Tool_v2.3.6-PyQt_Setup.exe"
InstallDir "D:\SFS_Pack_Tool"
InstallDirRegKey HKCU "${REGKEY}" "InstallDir"
RequestExecutionLevel user          ; 默认装 D 盘，不需要管理员；装到 Program Files 才需要
SetCompressor /SOLID lzma
SetCompressorDictSize 64

VIProductVersion "2.3.6.0"
VIAddVersionKey "ProductName"     "${APPNAME}"
VIAddVersionKey "FileDescription" "${APPNAME} 安装程序"
VIAddVersionKey "FileVersion"     "${APPVERSION}"
VIAddVersionKey "ProductVersion"  "${APPVERSION}"
VIAddVersionKey "CompanyName"     "${PUBLISHER}"
VIAddVersionKey "LegalCopyright"  "GPL-3.0"

!define MUI_ICON   "SFS_Pack_Tool_v22.ico"
!define MUI_UNICON "SFS_Pack_Tool_v22.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXENAME}"
!define MUI_FINISHPAGE_RUN_TEXT "装好了，现在打开 ${APPNAME}"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"

LangString DESC_MAIN ${LANG_SIMPCHINESE} "程序本体（必需）。装完即可双击运行，启动约 1 秒。"
LangString DESC_DESK   ${LANG_SIMPCHINESE} "在桌面放一个快捷方式。（会写入 C 盘的用户目录）"
LangString DESC_SM     ${LANG_SIMPCHINESE} "在开始菜单建一个文件夹。（会写入 C 盘的用户目录）"

Section "程序本体 (必需)" SEC_MAIN
  SectionIn RO
  SetOutPath "$INSTDIR"
  File /r "${SOURCEDIR}\*.*"

  ; 安装目录里的快捷方式，省得每次进文件夹找 exe
  CreateShortCut "$INSTDIR\${SHORTNAME}.lnk" "$INSTDIR\${EXENAME}" "" "$INSTDIR\${EXENAME}" 0
  WriteUninstaller "$INSTDIR\卸载.exe"

  WriteRegStr HKCU "${REGKEY}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${REGKEY}" "Version" "${APPVERSION}"

  ; 让 Windows「应用和功能」里能看到、能卸载
  WriteRegStr   HKCU "${UNINSTKEY}" "DisplayName"     "${APPNAME} ${APPVERSION}"
  WriteRegStr   HKCU "${UNINSTKEY}" "DisplayIcon"     "$INSTDIR\${EXENAME}"
  WriteRegStr   HKCU "${UNINSTKEY}" "Publisher"       "${PUBLISHER}"
  WriteRegStr   HKCU "${UNINSTKEY}" "DisplayVersion"  "${APPVERSION}"
  WriteRegStr   HKCU "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr   HKCU "${UNINSTKEY}" "UninstallString" '"$INSTDIR\卸载.exe"'
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoRepair" 1
SectionEnd

Section /o "桌面快捷方式" SEC_DESK
  CreateShortCut "$DESKTOP\${SHORTNAME}.lnk" "$INSTDIR\${EXENAME}" "" "$INSTDIR\${EXENAME}" 0
SectionEnd

Section /o "开始菜单快捷方式" SEC_SM
  CreateDirectory "$SMPROGRAMS\${SHORTNAME}"
  CreateShortCut "$SMPROGRAMS\${SHORTNAME}\${SHORTNAME}.lnk" "$INSTDIR\${EXENAME}" "" "$INSTDIR\${EXENAME}" 0
  CreateShortCut "$SMPROGRAMS\${SHORTNAME}\卸载 ${SHORTNAME}.lnk" "$INSTDIR\卸载.exe"
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_MAIN} $(DESC_MAIN)
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_DESK} $(DESC_DESK)
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_SM}   $(DESC_SM)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  Delete "$INSTDIR\${SHORTNAME}.lnk"
  Delete "$DESKTOP\${SHORTNAME}.lnk"
  Delete "$SMPROGRAMS\${SHORTNAME}\${SHORTNAME}.lnk"
  Delete "$SMPROGRAMS\${SHORTNAME}\卸载 ${SHORTNAME}.lnk"
  RMDir  "$SMPROGRAMS\${SHORTNAME}"

  RMDir /r "$INSTDIR"

  DeleteRegKey HKCU "${UNINSTKEY}"
  DeleteRegKey HKCU "${REGKEY}"
SectionEnd
