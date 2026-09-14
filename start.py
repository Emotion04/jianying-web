"""JianYing Editor Web - 一键启动 (纯 Python，跨平台)"""
import subprocess, sys, os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
SKILL_VENV = PROJECT_DIR / "skills" / "jianying-editor" / ".venv"

# Find Python
if (SKILL_VENV / "Scripts" / "python.exe").exists():
    python = str(SKILL_VENV / "Scripts" / "python.exe")
elif (SKILL_VENV / "bin" / "python3").exists():
    python = str(SKILL_VENV / "bin" / "python3")
else:
    python = sys.executable

print(f"Python: {python}")

# Install deps
for pkg in ["fastapi", "uvicorn", "httpx"]:
    try:
        __import__(pkg)
    except ImportError:
        print(f"Installing {pkg}...")
        subprocess.run([python, "-m", "pip", "install", pkg, "-q"])

# Start server
main_py = str(PROJECT_DIR / "backend" / "main.py")
print(f"Starting: {main_py}")
subprocess.run([python, main_py], cwd=str(PROJECT_DIR))
