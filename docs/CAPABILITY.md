# JianYing Editor Skill — 能力说明书

> **版本**: v1.0.0 | **平台**: Windows (完整) / macOS (部分) | **依赖**: 剪映专业版 + Python 3.8+

---

## 一、核心能力总览

jianying-editor 是剪映专业版的 Python 自动化封装，通过直接读写剪映的草稿 JSON 文件实现无头剪辑。你写的每个 Python 脚本最终变成一个剪映草稿，打开剪映就能看到、编辑、导出。

```
你的 Python 脚本  ──>  JyProject API  ──>  剪映草稿 JSON  ──>  剪映打开/导出
```

| 能力域 | 说明 | 复杂度 |
|--------|------|--------|
| 素材导入 | 视频/音频/图片进时间轴 | ⭐ |
| 文字标题 | 添加文字、字幕、带入场动画的标题 | ⭐ |
| 配乐 & TTS | 本地音乐、云端曲库、AI 配音生成 | ⭐⭐ |
| 特效/转场/滤镜 | 按名字搜索剪映内置特效库 | ⭐⭐ |
| 关键帧动画 | 缩放、位移、旋转、透明度关键帧 | ⭐⭐⭐ |
| 录屏 + 智能变焦 | 录制屏幕并自动生成点击位置的缩放动画 | ⭐⭐⭐ |
| Web 动效转视频 | HTML/JS/Canvas 动画渲染为透明视频素材 | ⭐⭐⭐ |
| 模板批量生产 | 克隆模板 → 替换素材 → 批量导出 | ⭐⭐ |
| 无头导出 | 通过 UI 自动化自动导出 MP4/SRT | ⭐⭐ |
| 复合片段 | 嵌套项目 (Compound Clip) 自动化 | ⭐⭐⭐ |

---

## 二、JyProject API 详解

### 2.1 项目初始化

```python
from jy_wrapper import JyProject

# 横屏（默认）
project = JyProject("我的项目", overwrite=True, width=1920, height=1080)

# 竖屏
project = JyProject("竖屏项目", overwrite=True, width=1080, height=1920)

# 从模板克隆
project = JyProject.from_template("母版模板", "客户A_成品")
```

### 2.2 素材操作 (MediaOpsMixin)

```python
# 添加视频/图片到时间轴
project.add_media_safe("video.mp4", start_time="0s", duration="5s", track_name="VideoTrack")

# 裁剪视频（从源素材的第3秒开始，取5秒）
project.add_clip("video.mp4", source_start="3s", duration="5s", target_start="0s")

# 添加音频
project.add_audio_safe("bgm.mp3", start_time="0s", duration="30s", track_name="AudioTrack")

# 云端素材（需要联网）
project.add_cloud_media("7546546694282676275", start_time="0s", duration="12s", track_name="BGM")
project.add_cloud_music("科技", start_time="0s", duration="10s")  # 按关键词搜索
```

### 2.3 文字与字幕 (TextOpsMixin)

```python
# 添加标题文字（带入场动画）
project.add_text_simple(
    text="Hello World",
    start_time="0.3s",
    duration="3s",
    font_size=18.0,
    color_rgb=(1.0, 1.0, 1.0),
    transform_y=-0.5,          # 垂直位置，-0.5=偏上居中
    anim_in="复古打字机",       # 入场动画
    track_name="TitleTrack",
)

# 可选入场动画:
# "复古打字机" | "弹簧" | "轻微放大" | "向上滑动" | "旋转飞入" | "模糊入场"

# 添加自定义字幕
project.add_subtitle("这是一条字幕", start_time="1s", duration="2s", track_name="Subtitles")
```

### 2.4 配音与旁白 (Audio & Voice)

```python
# 智能 TTS 配音
project.add_tts_intelligent(
    "欢迎来到 AI 剪辑教程",
    speaker="zh_male_huoli",
    start_time="0s",
    track_name="AudioTrack",
)

# 配音 + 字幕一键对齐
project.add_narrated_subtitles(
    "今天我们演示自动旁白与字幕的完美对齐",
    speaker="zh_female_xiaopengyou",
    start_time="1s",
)

# 可选发音人:
# zh_male_huoli | zh_female_xiaopengyou | zh_male_xionger_stream_gpu | zh_female_inspirational
```

### 2.5 特效与动效 (VfxOpsMixin)

```python
# 搜索特效、转场、滤镜
# CLI: python scripts/asset_search.py "复古" -c filters

# 添加特效
project.add_effect("模糊", start_time="2s", duration="1s")

# 添加转场
project.add_transition("淡入淡出", between_clip_1_and_2=True)

# 添加滤镜
project.add_filter("日系清新", track_name="VideoTrack")
```

### 2.6 关键帧动画 (Keyframes)

```python
# 缩放动画
project.add_zoom_keyframe(scale=1.5, start_time="2s", duration="1s")

# 自定义关键帧（位置、缩放、旋转、透明度）
project.add_keyframe(
    param="scale_x", values=[1.0, 1.5, 1.0],
    times=["0s", "1s", "2s"],
)
```
### 2.7 保存与导出

```python
# 保存草稿（必须调用）
project.save()

# 无头自动导出 MP4（需要剪映专业版运行）
# CLI: python scripts/auto_exporter.py "项目名" "output.mp4" --res 1080 --fps 60

# 仅导出 SRT 字幕
# CLI: python scripts/jy_wrapper.py export-srt --name "项目名"
```

---

## 三、高级能力

### 3.1 录屏 + 智能变焦

录制屏幕操作，自动在点击位置生成"放大-停留-恢复"的关键帧动画，适合做软件教程。

```
流程：启动录屏 → 操作演示 → 停止录屏 → 自动生成带缩放动画的剪映草稿
```

- Windows: `python tools/recording/recorder.py`
- macOS: `python tools/recording/macos_recorder.py`
- 手动应用变焦: `python scripts/jy_wrapper.py apply-zoom --name "项目" --video "v.mp4" --json "e.json"`

### 3.2 Web 动效转视频

用 HTML/CSS/JS 写动画，渲染成带透明通道的视频素材，突破剪映内置特效的限制。

```python
# 支持: GSAP 动画库 | Three.js 3D | Chart.js 图表 | Canvas 粒子 | Anime.js
project.add_web_asset_safe(html_path="vfx_scene.html", start_time="0s", duration="5s")
```

- 必须设置 `window.animationFinished = true` 通知录制器动画完成
- 默认透明背景，分辨率 1920x1080
- 超时时间 30 秒

### 3.3 批量模板生产

适合电商、营销号等需要大量个性化视频的场景：

```python
# 1. 从模板克隆
project = JyProject.from_template("酒店模板", "客户A_副本")

# 2. 替换素材（手动编辑 draft_content.json 中的素材路径）
# 3. 批量导出
```

### 3.4 影视解说自动生成

从分镜 JSON 自动生成 60 秒解说视频：

```bash
python scripts/movie_commentary_builder.py --video "movie.mp4" --json "storyboard.json"
```

---

## 四、CLI 工具清单

| 工具 | 用途 |
|------|------|
| `draft_inspector.py list --limit 20` | 列出所有草稿 |
| `draft_inspector.py show --name "Draft" --kind content --json` | 查看草稿详情 |
| `asset_search.py "复古" -c filters` | 搜索特效/转场/滤镜 |
| `sync_jy_assets.py` | 同步剪映 App 本地收藏的音乐 |
| `api_validator.py` | 一键诊断环境 |
| `auto_exporter.py "Draft" "out.mp4" --res 1080 --fps 60` | 无头导出 MP4 |
| `jy_wrapper.py clone --template "X" --name "Y"` | 克隆模板 |
| `jy_wrapper.py export-srt --name "Draft"` | 导出 SRT 字幕 |
| `jy_wrapper.py apply-zoom ...` | 录屏智能变焦 |
| `list_tts_speakers.py` | 列出所有 TTS 发音人 |
| `movie_commentary_builder.py` | 影视解说生成 |
| `video_analyzer.py` | AI 视频分析（30m/360p 优化） |

---

## 五、云端资源库

Skill 内置了剪映云端素材的索引数据库：

| 数据文件 | 内容 | 记录数 |
|----------|------|--------|
| `data/cloud_music_library.csv` | 云端背景音乐库 | 按风格/情绪/时长索引 |
| `data/cloud_sound_effects.csv` | 云端音效库 | 音效关键词索引 |
| `data/jy_cached_audio.csv` | 本地已同步的收藏音乐 | 用户个人收藏 |

```python
# 按关键词搜索并使用云端音乐
project.add_cloud_music("科技", start_time="0s", duration="15s")
# 或直接用云端 ID
project.add_cloud_media("7546546694282676275", start_time="0s", duration="12s")
```

---

## 六、环境要求

| 组件 | 要求 |
|------|------|
| 操作系统 | Windows 10/11 (完整支持) 或 macOS (部分支持) |
| Python | 3.8 ~ 3.14 |
| 剪映专业版 | Windows: v5.9 或更低 (导出功能)；macOS: 草稿仅 JSON |
| ffmpeg | 录屏和视频分析必需 |
| 网络 | 云端素材和 TTS 需要 |

---

## 七、本 Web 控制台已集成的能力

| 功能 | 模板模式 | 自定义模式 | AI 模式 |
|------|:---:|:---:|:---:|
| 视频素材导入 | ✅ | ✅ | ✅ |
| 背景音乐 | ✅ | - | ✅ |
| 标题文字 + 动画 | ✅ | ✅ | ✅ |
| TTS 配音 | 预留 | - | ✅ |
| 横/竖屏自适应 | ✅ | ✅ | ✅ |
| 自动检测视频方向 | ✅ | ✅ | - |
| AI 自然语言生成脚本 | - | - | ✅ |
| 自定义草稿目录 | ✅ | ✅ | ✅ |
| 批量生成 | 开发中 | - | - |
| 特效/转场 | - | - | ✅ (AI) |
| 录屏智能变焦 | - | - | ✅ (AI) |
| Web 动效 | - | - | ✅ (AI) |
| 电影解说 | - | - | ✅ (AI) |
| 无头自动导出 | ✅ | ✅ | ✅ |

> **说明**: 模板和自定义模式覆盖 80% 日常需求；复杂需求（特效、配音、录屏等）通过 AI 模式描述需求即可自动生成对应脚本。
