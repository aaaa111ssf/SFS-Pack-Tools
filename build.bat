@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ==========================================================
echo   SFS Pack Tool v2.3.3 - 打包脚本
echo ==========================================================

if "%1"=="-p" goto :prep_only

if not exist "third_party\assetripper-1.1.4\AssetRipper.GUI.Free.exe" goto :skip_unzip
echo [1/3] 内置 AssetRipper 已就绪，跳过解压
goto :deps

:skip_unzip
echo [1/3] 解压内置 AssetRipper 1.1.4 ...
if not exist "third_party\assetripper-1.1.4" mkdir "third_party\assetripper-1.1.4"
powershell -NoProfile -Command "Expand-Archive -Force -Path 'AssetRipper_win_x64-1.1.4.zip' -DestinationPath 'third_party\assetripper-1.1.4'"
if errorlevel 1 ( echo   解压失败！请确认 AssetRipper_win_x64-1.1.4.zip 存在 & pause & exit /b 1 )

:deps
echo [2/3] 检查打包依赖 ...
python -m PyInstaller --version >nul 2>nul
if not errorlevel 1 ( echo   PyInstaller 已安装，跳过联网下载 & goto :deps_ok )
echo   未检测到 PyInstaller，联网安装（如网络不通可手动装好后再运行）：
python -m pip install --upgrade pyinstaller UnityPy
if errorlevel 1 (
   echo   联网安装失败。请先手动执行下面的命令再重跑：
   echo   python -m pip install --upgrade pyinstaller UnityPy
   pause
   exit /b 1
)

:deps_ok
if not exist "licenses\LICENSE-GPL-3.0.txt" copy /y "LICENSE-GPL-3.0.txt" "licenses\" >nul
if not exist "licenses\GPL_COMPLIANCE.md" copy /y "GPL_COMPLIANCE.md" "licenses\" >nul

echo [3/3] 打包 EXE ...
python -m PyInstaller --noconfirm --clean SFS_Pack_Tool.spec
if errorlevel 1 ( echo   打包失败，请粘贴上方完整输出 & pause & exit /b 1 )

echo.
echo ==========================================================
echo   打包完成，EXE 位置：
echo   %cd%\dist\SFS_Pack_Tool_v2.3.3_Embedded_GPL.exe
echo   下一步运行 sign.bat 进行签名
echo ==========================================================
if exist "dist\SFS_Pack_Tool_v2.3.3_Embedded_GPL.exe" dir /b dist\*.exe
pause
exit /b 0
:prep_only
echo 仅预处理完成。直接打包请运行不带 -p 的参数。
pause
