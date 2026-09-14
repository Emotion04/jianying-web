"""
Vlog 快速剪辑模板
"""

class VlogTemplate:
    name = "Vlog 快速剪辑"
    description = "日常Vlog速剪：多片段拼接 → 转场 → 配乐 → 字幕"
    icon = "🎥"

    def fields(self) -> list[dict]:
        return [
            {
                "key": "video_files",
                "label": "视频素材",
                "type": "file",
                "accept": "video/*",
                "multiple": True,
                "required": True,
                "hint": "按顺序上传Vlog片段",
            },
            {
                "key": "audio_file",
                "label": "背景音乐",
                "type": "file",
                "accept": "audio/*",
                "required": False,
                "hint": "Vlog配乐，可选",
            },
            {
                "key": "title_text",
                "label": "Vlog 标题",
                "type": "text",
                "default": "我的日常",
                "required": False,
                "hint": "视频开头的Vlog标题",
            },
            {
                "key": "orientation",
                "label": "视频方向",
                "type": "select",
                "options": [
                    {"value": "vertical", "label": "竖屏 (9:16) - 抖音/快手"},
                    {"value": "horizontal", "label": "横屏 (16:9) - B站/YouTube"},
                ],
                "default": "vertical",
                "hint": "根据发布平台选择",
            },
            {
                "key": "clip_duration",
                "label": "每段时长（秒）",
                "type": "number",
                "default": 4,
                "min": 1,
                "max": 15,
                "hint": "每个片段在成片中的时长",
            },
            {
                "key": "project_name",
                "label": "项目名称",
                "type": "text",
                "default": "我的Vlog",
                "hint": "剪映中显示的草稿名称",
            },
        ]

    def generate(self, params: dict, project_name: str) -> str:
        files = params.get("_files", {})
        title = params.get("title_text", "我的日常")
        clip_duration = int(params.get("clip_duration", 4))

        lines = []

        # Collect video files
        video_files = []
        for key, path in files.items():
            if key.startswith("video"):
                video_files.append(path)
        if not video_files and "video_files" in files:
            vf = files["video_files"]
            video_files = [vf] if isinstance(vf, str) else vf

        # Add video clips sequentially
        if video_files:
            for i, vf in enumerate(video_files):
                start = f"{i * clip_duration}s"
                dur = f"{clip_duration}s"
                lines.append(f"project.add_media_safe(r'{vf}', '{start}', '{dur}', track_name='VideoTrack')")
        else:
            lines.append("# 未提供视频素材，请在剪映中手动添加素材")

        # Add audio
        total_dur = f"{len(video_files) * clip_duration}s" if video_files else "10s"
        if "audio_file" in files:
            audio_path = files["audio_file"]
            lines.append(f"project.add_audio_safe(r'{audio_path}', '0s', '{total_dur}', track_name='AudioTrack')")

        # Add title
        if title:
            lines.append("")
            lines.append(f"project.add_text_simple(")
            lines.append(f"    text={repr(title)},")
            lines.append(f'    start_time="0.2s",')
            lines.append(f'    duration="2.5s",')
            lines.append(f"    font_size=16.0,")
            lines.append(f"    color_rgb=(1, 1, 1),")
            lines.append(f"    transform_y=-0.55,")
            lines.append(f'    anim_in="向上滑动",')
            lines.append(f'    track_name="TitleTrack",')
            lines.append(f")")

        # Save
        lines.append("")
        lines.append("project.save()")

        return "\n".join(lines)
