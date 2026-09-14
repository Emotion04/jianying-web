"""
JianYing Editor Web - FastAPI Backend
======================================
模板生成 + AI代理 + 文件上传 + 草稿导出
复用 jianying-editor skill 的虚拟环境和 JyProject API
"""

import os
import sys
import json
import uuid
import shutil
import subprocess
import time
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import aiofiles

# ── Path Setup: detect jianying-editor skill root ──
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
SKILLS_DIR = PROJECT_ROOT / "skills"
SKILL_ROOT = SKILLS_DIR / "jianying-editor"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
UPLOADS_DIR = PROJECT_ROOT / "uploads"
FRONTEND_DIR = PROJECT_ROOT / "frontend"

# Add skill scripts to path
SKILL_SCRIPTS = SKILL_ROOT / "scripts"
if str(SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SKILL_SCRIPTS))

# Ensure directories exist
SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# ── Environment ──
os.environ["JY_SKILL_ROOT"] = str(SKILL_ROOT)

# ── FastAPI App ──
app = FastAPI(
    title="JianYing Editor Web",
    description="剪映自动化剪辑 Web 控制台",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════
# PROVIDER CONFIG
# ═══════════════════════════════════════════════════════════

PROVIDER_CONFIG = {
    "deepseek": {
        "url": "https://api.deepseek.com/chat/completions",
        "default_model": "deepseek-v4-flash",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "label": "DeepSeek",
    },
    "mimo": {
        "url": "https://token-plan-cn.xiaomimomo.com/v1/chat/completions",
        "default_model": "mimo-v2.5-pro",
        "auth_header": "api-key",
        "auth_prefix": "",
        "label": "小米 MiMo",
    },
    "qwen": {
        "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "default_model": "qwen3.6-flash",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "label": "通义千问",
    },
}

# Default system prompt for AI script generation
SYSTEM_PROMPT = """你是一个剪映自动化专家。用户会用自然语言描述视频剪辑需求，你需要生成可执行的 Python 代码。

## 环境已就绪（无需写初始化代码）

以下变量已在运行时环境中定义，**直接使用即可，不要重新定义**：

- `project`: `JyProject` 实例，已用项目名初始化，可直接调用方法
- `UPLOADS_DIR`: 上传文件目录的 Path 对象

## JyProject 可用方法

```python
# 素材导入
project.add_media_safe(path, start_time, duration, track_name="VideoTrack")
project.add_audio_safe(path, start_time, duration, track_name="AudioTrack")

# 文字/字幕
project.add_text_simple(text, start_time, duration, font_size=15.0,
                        color_rgb=(1,1,1), transform_y=-0.5, anim_in="复古打字机")

# 保存（必须调用）
project.save()
```

## 核心规则

1. **路径**：使用 `str(UPLOADS_DIR / "filename.mp4")` 拼接上传文件路径
2. **时间**：支持 "0s", "1.5s", "3s" 格式，duration 按素材实际时长
3. **分辨率**：默认 1920x1080，竖屏用 width=1080, height=1920
4. **必须调用 project.save()** 在脚本末尾
5. **只输出纯 Python 代码**，不要 markdown 代码块标记，不要解释文字

## 示例

用户需求："用 demo.mp4 的前5秒做一个带标题的片段"

输出：
```python
video = str(UPLOADS_DIR / "demo.mp4")
project.add_media_safe(video, "0s", "5s", track_name="VideoTrack")
project.add_text_simple("精彩片段", "0.3s", "3s", font_size=15.0,
                        color_rgb=(1,1,1), anim_in="复古打字机")
project.save()
print("Draft saved: " + project.name)
```

现在根据用户需求生成代码："""


# ═══════════════════════════════════════════════════════════
# UTILITIES
# ═══════════════════════════════════════════════════════════

def check_environment() -> dict:
    """Check if jianying-editor and JianYing are available."""
    issues = []
    ok = True

    # Check skill scripts
    jy_wrapper = SKILL_SCRIPTS / "jy_wrapper.py"
    if not jy_wrapper.exists():
        issues.append("jianying-editor skill 未找到，请先安装: git clone ... && pip install -r requirements.txt")
        ok = False

    # Check drafts root
    try:
        from utils.formatters import get_default_drafts_root
        drafts_root = get_default_drafts_root()
        if drafts_root and Path(drafts_root).exists():
            pass  # OK
        else:
            issues.append(f"剪映草稿目录不存在: {drafts_root}")
    except Exception as e:
        issues.append(f"无法检测剪映草稿目录: {e}")

    return {"ok": ok, "issues": issues, "skill_root": str(SKILL_ROOT)}


def execute_script(script_code: str, project_name: str = None, project_kwargs: dict = None) -> dict:
    """Execute a generated Python script using jianying-editor.

    Wraps user code with the proper bootstrap boilerplate so templates
    and AI-generated code can use JyProject directly.
    """
    if project_name is None:
        project_name = f"JianYing_Web_{uuid.uuid4().hex[:8]}"

    kwargs = project_kwargs or {}
    width = kwargs.get("width", 1920)
    height = kwargs.get("height", 1080)

    # Custom drafts root
    custom_root = _server_config.get("drafts_root", "")
    drafts_root_arg = f', drafts_root=r"{custom_root}"' if custom_root else ""

    # Normalize indentation and strip fences
    from textwrap import dedent
    clean_code = script_code.strip()
    if clean_code.startswith("```"):
        lines = clean_code.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        clean_code = "\n".join(lines)

    user_code = dedent(clean_code).strip()

    full_script = f'''"""
Auto-generated script for JianYing Editor
Project: {project_name}
"""
import os, sys
from pathlib import Path

# ── Bootstrap jianying-editor skill ──
SKILL_ROOT = Path(r"{SKILL_ROOT}")
SCRIPTS_PATH = SKILL_ROOT / "scripts"
if str(SCRIPTS_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_PATH))
os.environ["JY_SKILL_ROOT"] = str(SKILL_ROOT)

from jy_wrapper import JyProject

UPLOADS_DIR = Path(r"{UPLOADS_DIR}")

# ── Initialize project ──
project = JyProject({repr(project_name)}, overwrite=True, width={width}, height={height}{drafts_root_arg})

# ── User script ──
{user_code}

print("Draft saved: " + project.name)
'''

    # Write script to file (per skill rules: scripts in user project root)
    script_path = SCRIPTS_DIR / f"{project_name}.py"
    script_path.write_text(full_script, encoding="utf-8")

    # Execute
    venv_python = SKILL_ROOT / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        venv_python = SKILL_ROOT / ".venv" / "bin" / "python3"

    try:
        result = subprocess.run(
            [str(venv_python), str(script_path)],
            capture_output=True, text=True, timeout=120,
            cwd=str(PROJECT_ROOT),
            env={**os.environ, "JY_SKILL_ROOT": str(SKILL_ROOT),
                 "PYTHONPATH": str(SKILL_SCRIPTS)}
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "script_path": str(script_path),
            "project_name": project_name,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": "脚本执行超时 (120s)",
            "script_path": str(script_path),
            "project_name": project_name,
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(e),
            "script_path": str(script_path),
            "project_name": project_name,
        }


# ═══════════════════════════════════════════════════════════
# API ROUTES
# ═══════════════════════════════════════════════════════════

@app.get("/api/status")
async def api_status():
    """系统状态检查"""
    env = check_environment()
    try:
        from utils.formatters import get_default_drafts_root
        drafts_root = get_default_drafts_root()
    except:
        drafts_root = "unknown"

    return {
        "status": "ok" if env["ok"] else "issues",
        "environment": env,
        "drafts_root": str(drafts_root),
        "uploads_count": len(list(UPLOADS_DIR.glob("*"))) if UPLOADS_DIR.exists() else 0,
        "scripts_count": len(list(SCRIPTS_DIR.glob("*.py"))) if SCRIPTS_DIR.exists() else 0,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/templates")
async def api_list_templates():
    """列出所有可用模板"""
    from templates import TEMPLATE_REGISTRY
    templates = []
    for tid, tpl in TEMPLATE_REGISTRY.items():
        templates.append({
            "id": tid,
            "name": tpl.name,
            "description": tpl.description,
            "icon": tpl.icon,
            "fields": tpl.fields(),
        })
    return {"templates": templates}


@app.post("/api/generate/template")
async def api_generate_template(
    template_id: str = Form(...),
    params: str = Form("{}"),
    files: list[UploadFile] = File(default=[]),
):
    """使用模板生成剪辑脚本并执行"""
    from templates import TEMPLATE_REGISTRY

    if template_id not in TEMPLATE_REGISTRY:
        raise HTTPException(404, f"模板不存在: {template_id}")

    tpl = TEMPLATE_REGISTRY[template_id]
    parsed_params = json.loads(params) if isinstance(params, str) else params

    # Save uploaded files
    saved_files = {}
    for f in files:
        if f.filename:
            safe_name = f"{uuid.uuid4().hex[:8]}_{f.filename}"
            file_path = UPLOADS_DIR / safe_name
            content = await f.read()
            async with aiofiles.open(file_path, "wb") as out:
                await out.write(content)
            field_name = getattr(f, 'name', 'file')
            saved_files[field_name] = str(file_path)

    # Merge file paths into params
    parsed_params["_files"] = saved_files

    # Generate and execute
    try:
        project_name = parsed_params.get("project_name", f"JY_{template_id}_{uuid.uuid4().hex[:6]}")
        script_code = tpl.generate(parsed_params, project_name)

        # Extract resolution config for execute_script
        orientation = parsed_params.get("orientation", "horizontal")
        if orientation == "vertical":
            project_kwargs = {"width": 1080, "height": 1920}
        else:
            project_kwargs = {"width": 1920, "height": 1080}

        result = execute_script(script_code, project_name, project_kwargs=project_kwargs)
        result["template_id"] = template_id
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/generate/ai")
async def api_generate_ai(
    script_code: str = Form(...),
    project_name: str = Form(None),
    width: int = Form(1920),
    height: int = Form(1080),
):
    """执行 AI 生成的剪辑脚本"""
    project_name = project_name or f"JY_AI_{uuid.uuid4().hex[:8]}"
    result = execute_script(script_code, project_name,
                           project_kwargs={"width": width, "height": height})
    return result


@app.post("/api/chat")
async def api_chat(request: Request):
    """SSE 流式代理：转发到 AI Provider，返回 SSE 流"""
    body = await request.json()
    user_input = body.get("user_input", "")
    provider_id = body.get("provider", "deepseek")
    model = body.get("model", "")
    custom_base_url = body.get("base_url", "")

    # Resolve provider config
    cfg = PROVIDER_CONFIG.get(provider_id, PROVIDER_CONFIG["deepseek"])

    # API key priority: client header > server env
    client_key = request.headers.get("x-api-key", "")
    env_key = os.environ.get(f"{provider_id.upper()}_API_KEY", "")
    api_key = client_key or env_key

    if not api_key:
        return StreamingResponse(
            iter([f"data: {json.dumps({'error': '请先配置 {cfg[\"label\"]} API Key'})}\n\n"]),
            media_type="text/event-stream",
        )

    target_url = custom_base_url.rstrip("/") + "/chat/completions" if custom_base_url else cfg["url"]
    resolved_model = model or cfg["default_model"]

    payload = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
        ],
        "stream": True,
        "temperature": 0.7,
        "max_tokens": 4096,
    }

    async def event_stream():
        import httpx
        headers = {
            "Content-Type": "application/json",
            cfg["auth_header"]: f"{cfg['auth_prefix']}{api_key}",
        }
        accumulated = ""
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream("POST", target_url, json=payload, headers=headers) as resp:
                    if resp.status_code != 200:
                        error_text = await resp.aread()
                        yield f"data: {json.dumps({'error': f'API 返回 {resp.status_code}: {error_text.decode()[:200]}'})}\n\n"
                        return
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                yield f"data: {json.dumps({'done': True, 'full': accumulated})}\n\n"
                                return
                            try:
                                chunk = json.loads(data)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    accumulated += content
                                    yield f"data: {json.dumps({'token': content})}\n\n"
                            except json.JSONDecodeError:
                                pass
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/test-connection")
async def api_test_connection(request: Request):
    """Test provider API connection with a minimal request. Returns plain JSON."""
    body = await request.json()
    provider_id = body.get("provider", "deepseek")
    model = body.get("model", "")
    custom_base_url = body.get("base_url", "")

    cfg = PROVIDER_CONFIG.get(provider_id, PROVIDER_CONFIG["deepseek"])
    client_key = request.headers.get("x-api-key", "")
    env_key = os.environ.get(f"{provider_id.upper()}_API_KEY", "")
    api_key = client_key or env_key

    if not api_key:
        return JSONResponse({"ok": False, "error": f"请先配置 {cfg['label']} API Key"}, status_code=400)

    target_url = custom_base_url.rstrip("/") + "/chat/completions" if custom_base_url else cfg["url"]
    resolved_model = model or cfg["default_model"]

    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                target_url,
                json={
                    "model": resolved_model,
                    "messages": [{"role": "user", "content": "OK"}],
                    "max_tokens": 5,
                    "stream": False,
                },
                headers={
                    "Content-Type": "application/json",
                    cfg["auth_header"]: f"{cfg['auth_prefix']}{api_key}",
                },
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return {"ok": True, "model": resolved_model, "provider": cfg["label"],
                        "response": content[:100]}
            else:
                error_detail = resp.text[:300]
                return JSONResponse(
                    {"ok": False, "error": f"API 返回 {resp.status_code}: {error_detail}"},
                    status_code=502
                )
    except Exception as e:
        return JSONResponse(
            {"ok": False, "error": f"连接失败: {str(e)}"},
            status_code=502
        )


@app.post("/api/media/upload")
async def api_upload_media(files: list[UploadFile] = File(...)):
    """上传媒体文件"""
    saved = []
    for f in files:
        if f.filename:
            safe_name = f"{uuid.uuid4().hex[:8]}_{f.filename}"
            file_path = UPLOADS_DIR / safe_name
            content = await f.read()
            async with aiofiles.open(file_path, "wb") as out:
                await out.write(content)
            saved.append({
                "original_name": f.filename,
                "saved_path": str(file_path),
                "size": len(content),
                "url": f"/api/media/{safe_name}",
            })
    return {"files": saved}


@app.get("/api/media/{filename}")
async def api_get_media(filename: str):
    """获取上传的媒体文件"""
    file_path = UPLOADS_DIR / filename
    if not file_path.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(file_path)


@app.get("/api/drafts")
async def api_list_drafts():
    """列出剪映中的现有草稿"""
    try:
        from utils.formatters import get_all_drafts, get_default_drafts_root
        drafts = get_all_drafts()
        return {
            "drafts_root": get_default_drafts_root(),
            "drafts": [{"name": d} for d in drafts] if isinstance(drafts, list) else [],
        }
    except Exception as e:
        return {"drafts_root": "unknown", "drafts": [], "error": str(e)}


@app.post("/api/export")
async def api_export_draft(
    draft_name: str = Form(...),
    output_name: str = Form(None),
    resolution: str = Form("1080"),
    fps: int = Form(60),
):
    """导出草稿为 MP4（需要剪映专业版运行）"""
    output_name = output_name or f"{draft_name}.mp4"
    if not output_name.endswith(".mp4"):
        output_name += ".mp4"
    output_path = UPLOADS_DIR / output_name

    exporter = SKILL_SCRIPTS / "auto_exporter.py"
    if not exporter.exists():
        raise HTTPException(500, "auto_exporter.py 未找到")

    venv_python = SKILL_ROOT / ".venv" / "Scripts" / "python.exe"

    try:
        result = subprocess.run(
            [str(venv_python), str(exporter), draft_name, str(output_path),
             "--res", resolution, "--fps", str(fps)],
            capture_output=True, text=True, timeout=300,
            env={**os.environ, "JY_SKILL_ROOT": str(SKILL_ROOT)}
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "output_path": str(output_path),
            "output_url": f"/api/media/{output_name}",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "导出超时 (300s)，请确认剪映已打开且草稿可访问"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/preview")
async def api_preview_script(
    template_id: Optional[str] = Form(None),
    params: str = Form("{}"),
    ai_script: Optional[str] = Form(None),
):
    """预览生成的脚本（不执行）"""
    if ai_script:
        return {"script": ai_script, "mode": "ai"}

    if template_id:
        from templates import TEMPLATE_REGISTRY
        if template_id not in TEMPLATE_REGISTRY:
            raise HTTPException(404, f"模板不存在: {template_id}")
        tpl = TEMPLATE_REGISTRY[template_id]
        parsed_params = json.loads(params) if isinstance(params, str) else params
        project_name = parsed_params.get("project_name", f"JY_Preview_{uuid.uuid4().hex[:6]}")
        script_code = tpl.generate(parsed_params, project_name)
        return {"script": script_code, "mode": "template", "template_id": template_id}

    raise HTTPException(400, "请提供 template_id 或 ai_script")


# ═══════════════════════════════════════════════════════════
# UTILITY ENDPOINTS
# ═══════════════════════════════════════════════════════════

# Server-side config (runtime only, not persisted to file)
_server_config = {"drafts_root": ""}


@app.get("/api/config")
async def api_get_config():
    """Get current server config"""
    try:
        from utils.formatters import get_default_drafts_root
        default_root = get_default_drafts_root()
    except:
        default_root = "unknown"
    return {
        "drafts_root": _server_config["drafts_root"] or default_root,
        "default_drafts_root": default_root,
        "is_custom": bool(_server_config["drafts_root"]),
    }


@app.post("/api/config")
async def api_set_config(request: Request):
    """Set server config (drafts root)"""
    body = await request.json()
    if "drafts_root" in body:
        _server_config["drafts_root"] = body["drafts_root"]
    return {"ok": True, "drafts_root": _server_config["drafts_root"]}


@app.post("/api/open-folder")
async def api_open_folder(request: Request):
    """Open a folder in system file explorer (local desktop only)"""
    body = await request.json()
    folder_path = body.get("path", "")
    if not folder_path:
        folder_path = body.get("type", "")
    path_map = {
        "uploads": str(UPLOADS_DIR),
        "scripts": str(SCRIPTS_DIR),
        "project": str(PROJECT_ROOT),
    }
    target = path_map.get(folder_path, folder_path)
    if not target or not Path(target).exists():
        return {"ok": False, "error": f"路径不存在: {target}"}
    try:
        os.startfile(str(Path(target)))
        return {"ok": True, "path": str(Path(target))}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/media/info")
async def api_media_info(files: list[UploadFile] = File(...)):
    """Get media file info (resolution, duration) for orientation detection"""
    results = []
    for f in files:
        if not f.filename:
            continue
        # Save temp file
        tmp_path = UPLOADS_DIR / f"__tmp_{uuid.uuid4().hex[:8]}_{f.filename}"
        content = await f.read()
        async with aiofiles.open(tmp_path, "wb") as out:
            await out.write(content)

        info = {"filename": f.filename, "size": len(content)}
        # Try to get video info via ffprobe
        try:
            import subprocess as sp
            r = sp.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(tmp_path)],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0:
                probe = json.loads(r.stdout)
                for stream in probe.get("streams", []):
                    if stream.get("codec_type") == "video":
                        w = stream.get("width", 0)
                        h = stream.get("height", 0)
                        info["width"] = w
                        info["height"] = h
                        info["orientation"] = "vertical" if h > w else "horizontal"
                        info["aspect"] = f"{w}x{h}"
                        # Get duration
                        dur = stream.get("duration") or probe.get("format", {}).get("duration")
                        if dur:
                            info["duration_seconds"] = float(dur)
                        break
        except Exception:
            pass

        # Keep the file if it was already uploaded; otherwise clean up
        if f.filename not in [uf.name for uf in []]:
            pass  # keep tmp file, upload endpoint can overwrite

        results.append(info)

    return {"files": results}


# ═══════════════════════════════════════════════════════════
# SERVE FRONTEND
# ═══════════════════════════════════════════════════════════

@app.get("/")
async def serve_frontend():
    """Serve the main frontend page"""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Frontend not found. Place index.html in frontend/</h1>")

# Mount static files (for uploaded media)
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")


# ═══════════════════════════════════════════════════════════
# 电商视频路由 — 独立端点，自由组合
# ═══════════════════════════════════════════════════════════

sys.path.insert(0, str(BACKEND_DIR))
from ecommerce.srt_handler import (
    SrtSegment, parse_srt, parse_srt_content, write_srt,
    segments_from_text, segments_to_text,
)
from ecommerce.video_processor import VideoProcessor
from ecommerce.segment_arranger import SegmentArranger

_asr_config = {
    "asr_engine": os.environ.get("ASR_ENGINE", "whisper"),
    "whisper_model": os.environ.get("WHISPER_MODEL", "base"),
    "whisper_device": os.environ.get("WHISPER_DEVICE", "cpu"),
    "aliyun_asr_app_key": os.environ.get("ALIYUN_ASR_APP_KEY", ""),
    "aliyun_asr_access_key_id": os.environ.get("ALIYUN_ASR_ACCESS_KEY_ID", ""),
    "aliyun_asr_access_key_secret": os.environ.get("ALIYUN_ASR_ACCESS_KEY_SECRET", ""),
}


# ── 字幕来源 ──

@app.post("/api/subtitle/parse-srt")
async def api_subtitle_parse_srt(files: list[UploadFile] = File(...)):
    """解析上传的 SRT 文件，返回 segments JSON"""
    if not files or not files[0].filename:
        raise HTTPException(400, "请上传 SRT 文件")
    content = (await files[0].read()).decode("utf-8")
    try:
        segs = parse_srt_content(content)
    except:
        raise HTTPException(400, "SRT 格式解析失败")
    return {
        "segments": [s.to_dict() for s in segs],
        "srt_content": content,
        "count": len(segs),
    }


@app.post("/api/subtitle/transcribe")
async def api_subtitle_transcribe(
    video_path: str = Form(""),
    files: list[UploadFile] = File(default=[]),
):
    """语音转文字：提取音频 → ASR → 返回 SRT"""
    if files and files[0].filename:
        f = files[0]
        safe_name = f"{uuid.uuid4().hex[:8]}_{f.filename}"
        file_path = UPLOADS_DIR / safe_name
        async with aiofiles.open(file_path, "wb") as out:
            await out.write(await f.read())
        video_path = str(file_path)
    if not video_path or not Path(video_path).exists():
        raise HTTPException(400, "视频文件不存在")

    work_dir = UPLOADS_DIR / f"asr_{uuid.uuid4().hex[:8]}"
    work_dir.mkdir(exist_ok=True)

    vp = VideoProcessor()
    audio_path = work_dir / "audio.wav"
    vp.extract_audio(video_path, str(audio_path))

    engine_type = _asr_config.get("asr_engine", "whisper")
    if engine_type == "aliyun" and not _asr_config.get("aliyun_asr_app_key"):
        return {"success": False, "error": "未配置阿里云 ASR。可通过设置切换为本地 Whisper（免费）。"}

    from ecommerce.asr import create_asr_engine
    engine = create_asr_engine(_asr_config)
    try:
        raw = await engine.transcribe(str(audio_path))
    except Exception as e:
        return {"success": False, "error": f"ASR 转写失败: {str(e)}"}

    if not raw:
        return {"success": False, "error": "未识别到语音内容"}

    segs = [SrtSegment(index=i+1, start=s.start, end=s.end, text=s.text) for i, s in enumerate(raw)]
    srt_path = work_dir / "transcript.srt"
    write_srt(segs, str(srt_path))
    srt_content = srt_path.read_text(encoding="utf-8")

    return {
        "success": True,
        "srt_content": srt_content,
        "segments": [s.to_dict() for s in segs],
        "count": len(segs),
        "duration": segs[-1].end if segs else 0,
    }


@app.post("/api/subtitle/ai-generate")
async def api_subtitle_ai_generate(request: Request):
    """AI 生成带货文案 → 返回文本/SRT"""
    body = await request.json()
    product_info = body.get("product_info", "")
    style = body.get("style", "种草")  # 种草/捡漏/效果/对比
    provider = body.get("provider", "")
    model = body.get("model", "")

    client_key = request.headers.get("x-api-key", "")
    api_key = client_key or os.environ.get(f"{provider.upper()}_API_KEY", "")
    if not api_key:
        raise HTTPException(400, "请先配置 AI Provider")

    from ecommerce.copy_writer import CopyWriter
    writer = CopyWriter(provider=provider or "deepseek", model=model, api_key=api_key)

    try:
        result = await writer.generate_no_voiceover_copy(product_info, count=1)
        return {"success": True, **result}
    except Exception as e:
        raise HTTPException(500, f"AI 生成失败: {str(e)}")


# ── 渲染端点 ──

def _resolve_video_path(video_path: str, files: list) -> str:
    """解析视频路径（支持上传或已有路径）"""
    if files and files[0].filename:
        f = files[0]
        path = UPLOADS_DIR / f"{uuid.uuid4().hex[:8]}_{f.filename}"
        # sync write (called from async but files are small after upload)
        with open(path, "wb") as out:
            out.write(f.file.read())
        return str(path)
    if video_path and Path(video_path).exists():
        return video_path
    raise HTTPException(400, "请提供视频文件")


def _str_to_segments(s: str) -> list:
    """将 SRT 文本或 JSON 转为 segments 列表，失败返回空"""
    s = s.strip()
    if not s:
        return []
    if s.startswith("{"):
        try:
            d = json.loads(s)
            items = d if isinstance(d, list) else d.get("segments", [])
            return [SrtSegment(i+1, it["start"], it["end"], it["text"]) for i, it in enumerate(items)]
        except:
            pass
    try:
        return parse_srt_content(s)
    except:
        pass
    # Plain text: split by lines
    lines = [l.strip() for l in s.split("\n") if l.strip()]
    dur = 3.0
    return [SrtSegment(i+1, i*dur, (i+1)*dur, l) for i, l in enumerate(lines)]


@app.post("/api/render/burn-subtitles")
async def api_render_burn_subtitles(
    video_path: str = Form(""),
    srt_content: str = Form(""),
    font_size: int = Form(24),
    font_color: str = Form("white"),
    font_name: str = Form("Microsoft YaHei"),
    files: list[UploadFile] = File(default=[]),
):
    """烧录字幕到视频 → 返回 MP4"""
    vp = _resolve_video_path(video_path, files)
    if not srt_content.strip():
        raise HTTPException(400, "请提供字幕内容")

    work_dir = UPLOADS_DIR / f"burn_{uuid.uuid4().hex[:6]}"
    work_dir.mkdir(exist_ok=True)

    # Write SRT file
    segs = _str_to_segments(srt_content)
    srt_path = work_dir / "subs.srt"
    write_srt(segs, str(srt_path))

    # Burn
    processor = VideoProcessor()
    color_map = {"white": "&H00FFFFFF", "black": "&H00000000", "red": "&H000000FF",
                 "yellow": "&H0000FFFF", "blue": "&H00FF0000", "green": "&H0000FF00"}
    fc = color_map.get(font_color, "&H00FFFFFF")
    out = work_dir / "output.mp4"
    processor.burn_subtitles(vp, str(srt_path), str(out),
                             font_name=font_name, font_size=font_size, font_color=fc)

    final = UPLOADS_DIR / f"burned_{uuid.uuid4().hex[:6]}.mp4"
    import shutil; shutil.copy(out, final)
    return {"success": True, "output_url": f"/api/media/{final.name}", "segments": len(segs)}


@app.post("/api/render/add-overlays")
async def api_render_add_overlays(
    video_path: str = Form(""),
    overlays_json: str = Form("[]"),
    files: list[UploadFile] = File(default=[]),
):
    """给视频添加品描叠加文字 → 返回 MP4"""
    vp = _resolve_video_path(video_path, files)
    overlays = json.loads(overlays_json) if isinstance(overlays_json, str) else overlays_json
    if not overlays:
        raise HTTPException(400, "请提供叠加文字")

    work_dir = UPLOADS_DIR / f"overlay_{uuid.uuid4().hex[:6]}"
    work_dir.mkdir(exist_ok=True)

    processor = VideoProcessor()
    out = work_dir / "output.mp4"
    processor.add_overlay_text(vp, overlays, str(out))

    final = UPLOADS_DIR / f"overlaid_{uuid.uuid4().hex[:6]}.mp4"
    import shutil; shutil.copy(out, final)
    return {"success": True, "output_url": f"/api/media/{final.name}", "count": len(overlays)}


@app.post("/api/render/remix")
async def api_render_remix(
    video_path: str = Form(""),
    srt_content: str = Form(""),
    plan_json: str = Form("{}"),
    font_size: int = Form(24),
    files: list[UploadFile] = File(default=[]),
):
    """口播混剪：切段 → AI重排 → 拼接 → 烧字幕 → 返回 MP4"""
    vp = _resolve_video_path(video_path, files)
    segs = _str_to_segments(srt_content)
    if not segs:
        raise HTTPException(400, "请提供字幕用于切段")

    plan = json.loads(plan_json) if isinstance(plan_json, str) else plan_json
    arrangement = plan.get("arrangement", plan) if isinstance(plan, dict) else {}
    if not arrangement.get("order"):
        arrangement["order"] = list(range(len(segs)))

    work_dir = UPLOADS_DIR / f"remix_{uuid.uuid4().hex[:6]}"
    work_dir.mkdir(exist_ok=True)

    processor = VideoProcessor()
    arranger = SegmentArranger(processor)
    arranger.set_work_dir(work_dir)

    result = arranger.process_pipeline(vp, segs, arrangement,
                                        subtitle_style={"font_size": font_size})

    final = UPLOADS_DIR / f"remixed_{uuid.uuid4().hex[:6]}.mp4"
    import shutil; shutil.copy(result["video_path"], final)
    return {
        "success": True,
        "output_url": f"/api/media/{final.name}",
        "segments": result["segments_count"],
        "duration": result["duration"],
    }


@app.post("/api/render/combined")
async def api_render_combined(
    video_path: str = Form(""),
    srt_content: str = Form(""),
    overlays_json: str = Form("[]"),
    enable_remix: bool = Form(False),
    plan_json: str = Form("{}"),
    font_size: int = Form(24),
    font_color: str = Form("white"),
    font_name: str = Form("Microsoft YaHei"),
    subtitle_align: str = Form("2"),
    outline_color: str = Form("&H80000000"),
    outline_width: str = Form("2"),
    margin_v: str = Form("40"),
    shadow: str = Form("0"),
    bold: str = Form("0"),
    italic: str = Form("0"),
    border_style: str = Form("1"),
    files: list[UploadFile] = File(default=[]),
):
    """
    一键全流程：可选字幕 + 可选品描 + 可选混剪 → 一个 MP4。
    所有参数均可空，后端依次执行有值步骤。
    """
    import shutil
    vp = _resolve_video_path(video_path, files)
    work_dir = UPLOADS_DIR / f"combined_{uuid.uuid4().hex[:6]}"
    work_dir.mkdir(exist_ok=True)
    processor = VideoProcessor()
    current_video = vp
    steps_done = []

    # Step 1: Remix (if enabled and has subtitles)
    if enable_remix and srt_content.strip():
        segs = _str_to_segments(srt_content)
        if segs:
            plan = json.loads(plan_json) if isinstance(plan_json, str) else plan_json
            arr = (plan.get("arrangement", plan) if isinstance(plan, dict) else {})
            if not arr.get("order"):
                arr["order"] = list(range(len(segs)))
            arranger = SegmentArranger(processor)
            arranger.set_work_dir(work_dir)
            r = arranger.process_pipeline(vp, segs, arr, subtitle_style={"font_size": font_size, "font_color": font_color, "font_name": font_name})
            current_video = r["video_path"]
            steps_done.append(f"混剪({len(segs)}段)")

    # Step 2: Burn subtitles (if not remixed, remix already burns them)
    if srt_content.strip() and not enable_remix:
        segs = _str_to_segments(srt_content)
        if segs:
            srt_path = work_dir / "subs.srt"
            write_srt(segs, str(srt_path))
            color_map = {"white": "&H00FFFFFF", "black": "&H00000000", "red": "&H000000FF",
                         "yellow": "&H0000FFFF", "blue": "&H00FF0000", "green": "&H0000FF00"}
            fc = color_map.get(font_color, "&H00FFFFFF")
            subbed = str(work_dir / "subbed.mp4")
            processor.burn_subtitles(current_video, str(srt_path), subbed,
                                     font_name=font_name, font_size=font_size, font_color=fc)
            current_video = subbed
            steps_done.append(f"字幕({len(segs)}条)")

    # Step 3: Add overlays
    overlays = json.loads(overlays_json) if isinstance(overlays_json, str) else overlays_json
    if overlays and isinstance(overlays, list) and len(overlays) > 0:
        overlaid = str(work_dir / "overlaid.mp4")
        processor.add_overlay_text(current_video, overlays, overlaid)
        current_video = overlaid
        steps_done.append(f"品描({len(overlays)}条)")

    # If nothing was done, just copy the original
    if not steps_done:
        steps_done.append("原视频(无处理)")

    final = UPLOADS_DIR / f"final_{uuid.uuid4().hex[:6]}.mp4"
    shutil.copy(current_video, final)

    return {
        "success": True,
        "output_url": f"/api/media/{final.name}",
        "steps": steps_done,
    }


# ── 预览 ──

@app.post("/api/render/preview")
async def api_render_preview(
    video_path: str = Form(""),
    srt_content: str = Form(""),
    overlays_json: str = Form("[]"),
    font_size: int = Form(24),
    font_color: str = Form("white"),
    font_name: str = Form("Microsoft YaHei"),
    subtitle_align: str = Form("2"),
    outline_color: str = Form("&H80000000"),
    outline_width: str = Form("2"),
    margin_v: str = Form("40"),
    shadow: str = Form("0"),
    bold: str = Form("0"),
    files: list[UploadFile] = File(default=[]),
):
    """
    预览：截取视频第一帧，叠加字幕+品描，返回 PNG 图片。
    秒级出图，用于预览样式。
    """
    vp = _resolve_video_path(video_path, files)
    work_dir = UPLOADS_DIR / f"preview_{uuid.uuid4().hex[:6]}"
    work_dir.mkdir(exist_ok=True)
    processor = VideoProcessor()

    # Get frame
    frame_path = work_dir / "frame.png"
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", vp, "-vframes", "1", "-q:v", "2", str(frame_path)],
        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise HTTPException(500, f"截帧失败: {r.stderr[:200]}")

    current = str(frame_path)

    # Burn subtitles on frame
    if srt_content.strip():
        segs = _str_to_segments(srt_content)
        if segs:
            srt_path = work_dir / "preview.srt"
            write_srt(segs, str(srt_path))
            color_map = {"white": "&H00FFFFFF", "black": "&H00000000", "red": "&H000000FF",
                         "yellow": "&H0000FFFF", "blue": "&H00FF0000", "green": "&H0000FF00"}
            fc = color_map.get(font_color, "&H00FFFFFF")
            subbed = str(work_dir / "subbed.png")
            oc = outline_color if outline_color != 'none' else '&H00000000'
            ow = int(outline_width) if outline_color != 'none' else 0
            processor.burn_subtitles(current, str(srt_path), subbed,
                                     font_name=font_name, font_size=int(font_size),
                                     font_color=fc, outline_color=oc,
                                     outline_width=ow, alignment=int(subtitle_align),
                                     margin_v=int(margin_v), shadow=int(shadow),
                                     bold=bold, italic=italic)
            current = subbed

    # Add overlays
    overlays = json.loads(overlays_json) if isinstance(overlays_json, str) else overlays_json
    if overlays and isinstance(overlays, list) and len(overlays) > 0:
        overlaid = str(work_dir / "overlaid.png")
        processor.add_overlay_text(current, overlays, overlaid)
        current = overlaid

    final_name = f"preview_{uuid.uuid4().hex[:6]}.png"
    import shutil; shutil.copy(current, UPLOADS_DIR / final_name)
    return {"success": True, "preview_url": f"/api/media/{final_name}"}


# ── 导出 ──

@app.post("/api/export/srt")
async def api_export_srt(text: str = Form("")):
    """将文本或 SRT 内容导出为 .srt 文件下载"""
    if not text.strip():
        raise HTTPException(400, "没有可导出的内容")
    segs = _str_to_segments(text)
    out = UPLOADS_DIR / f"export_{uuid.uuid4().hex[:6]}.srt"
    write_srt(segs, str(out))
    return FileResponse(str(out), media_type="text/plain", filename="subtitles.srt")


@app.post("/api/export/txt")
async def api_export_txt(text: str = Form("")):
    """将文本内容导出为 .txt 文件下载（纯文本，无时间戳）"""
    if not text.strip():
        raise HTTPException(400, "没有可导出的内容")
    segs = _str_to_segments(text)
    plain = "\n".join(s.text for s in segs)
    out = UPLOADS_DIR / f"export_{uuid.uuid4().hex[:6]}.txt"
    out.write_text(plain, encoding="utf-8")
    return FileResponse(str(out), media_type="text/plain", filename="subtitles.txt")


# ═══════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    print(f"\n{'='*60}")
    print(f"  🎬 JianYing Editor Web")
    print(f"  Skill Root : {SKILL_ROOT}")
    print(f"  Uploads    : {UPLOADS_DIR}")
    print(f"  Scripts    : {SCRIPTS_DIR}")
    print(f"{'='*60}\n")

    env = check_environment()
    if env["ok"]:
        print("✅ 环境检测通过")
    else:
        print("⚠️  环境问题:")
        for issue in env["issues"]:
            print(f"   - {issue}")

    print(f"\n  打开浏览器访问: http://localhost:8000\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
