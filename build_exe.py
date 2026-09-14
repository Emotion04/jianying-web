"""
PyInstaller 打包脚本
====================
将整个项目打包为单个 .exe 文件，包含：
- FastAPI 后端
- jianying-editor skill
- 前端静态页面
- Python 运行时

用法：
    python build_exe.py          # 打包为文件夹 (推荐，启动快)
    python build_exe.py --onefile # 打包为单文件
"""

import os
import sys
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SKILL_ROOT = PROJECT_ROOT / "skills" / "jianying-editor"
VENV_PYTHON = SKILL_ROOT / ".venv" / "Scripts" / "python.exe"

def clean():
    """清理之前的构建"""
    for d in ["build", "dist"]:
        p = PROJECT_ROOT / d
        if p.exists():
            shutil.rmtree(p)
    for spec in PROJECT_ROOT.glob("*.spec"):
        spec.unlink()

def build(onefile=False):
    """执行 PyInstaller 构建"""
    cmd = [
        str(VENV_PYTHON), "-m", "PyInstaller",
        "--name", "JianYingEditorWeb",
        "--add-data", f"{PROJECT_ROOT / 'backend'};backend",
        "--add-data", f"{PROJECT_ROOT / 'frontend'};frontend",
        "--add-data", f"{SKILL_ROOT};skills/jianying-editor",
        "--add-data", f"{PROJECT_ROOT / 'scripts'};scripts",
        "--add-data", f"{PROJECT_ROOT / 'uploads'};uploads",
        "--hidden-import", "fastapi",
        "--hidden-import", "uvicorn",
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "python_multipart",
        "--hidden-import", "aiofiles",
        "--hidden-import", "httpx",
        "--hidden-import", "starlette",
        "--hidden-import", "pydantic",
        # jianying-editor imports
        "--hidden-import", "uiautomation",
        "--hidden-import", "pynput",
        "--hidden-import", "pyJianYingDraft",
        "--hidden-import", "numpy",
        "--collect-all", "pyJianYingDraft",
        "--collect-all", "uiautomation",
        "--noconsole",
        str(PROJECT_ROOT / "backend" / "main.py"),
    ]

    if onefile:
        cmd.insert(4, "--onefile")

    print(f"\n{'='*60}")
    print(f"  构建模式: {'单文件' if onefile else '文件夹 (推荐)'}")
    print(f"  项目路径: {PROJECT_ROOT}")
    print(f"{'='*60}\n")

    os.chdir(str(PROJECT_ROOT))
    os.system(" ".join(cmd))

    # Post-build: copy skill data directories
    dist_dir = PROJECT_ROOT / "dist" / "JianYingEditorWeb"
    if onefile:
        print("\n✅ 构建完成: dist/JianYingEditorWeb.exe")
    else:
        print(f"\n✅ 构建完成: {dist_dir}")
        print(f"   双击 {dist_dir / 'JianYingEditorWeb.exe'} 启动")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--onefile", action="store_true", help="打包为单文件")
    parser.add_argument("--clean", action="store_true", help="清理构建目录")
    args = parser.parse_args()

    if args.clean:
        clean()
        print("✅ 清理完成")
    else:
        clean()
        build(onefile=args.onefile)
