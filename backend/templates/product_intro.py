"""
产品介绍视频模板
"""

class ProductIntroTemplate:
    name = "产品介绍"
    description = "制作产品展示视频：导入素材 → 配乐 → 标题文字 → 可选TTS配音"
    icon = "📦"

    def fields(self) -> list[dict]:
        return [
            {
                "key": "video_files",
                "label": "产品视频素材",
                "type": "file",
                "accept": "video/*",
                "multiple": True,
                "required": True,
                "hint": "选择一个或多个产品展示视频片段",
            },
            {
                "key": "audio_file",
                "label": "背景音乐",
                "type": "file",
                "accept": "audio/*",
                "required": False,
                "hint": "可选，不上传则使用默认音乐",
            },
            {
                "key": "title_text",
                "label": "标题文字",
                "type": "text",
                "default": "产品演示",
                "required": True,
                "hint": "显示在视频开头的标题",
            },
            {
                "key": "animation",
                "label": "标题动画",
                "type": "select",
                "options": [
                    {"value": "复古打字机", "label": "打字机"},
                    {"value": "弹簧", "label": "弹簧弹入"},
                    {"value": "轻微放大", "label": "淡入放大"},
                    {"value": "向上滑动", "label": "上滑淡入"},
                    {"value": "旋转飞入", "label": "旋转飞入"},
                ],
                "default": "复古打字机",
                "hint": "标题出现时的动效",
            },
            {
                "key": "orientation",
                "label": "视频方向",
                "type": "select",
                "options": [
                    {"value": "horizontal", "label": "横屏 (16:9)"},
                    {"value": "vertical", "label": "竖屏 (9:16)"},
                ],
                "default": "horizontal",
                "hint": "根据产品展示平台选择",
            },
            {
                "key": "video_duration",
                "label": "每组素材时长（秒）",
                "type": "number",
                "default": 5,
                "min": 2,
                "max": 30,
                "hint": "每个视频片段的展示时间",
            },
            {
                "key": "tts_text",
                "label": "AI配音文案（可选）",
                "type": "textarea",
                "default": "",
                "hint": "输入配音文案，将自动生成TTS语音并添加字幕。留空则跳过",
            },
            {
                "key": "project_name",
                "label": "项目名称",
                "type": "text",
                "default": "产品介绍",
                "hint": "剪映中显示的草稿名称",
            },
        ]

    def generate(self, params: dict, project_name: str) -> str:
        files = params.get("_files", {})
        title = params.get("title_text", "产品演示")
        animation = params.get("animation", "复古打字机")
        duration = int(params.get("video_duration", 5))
        tts_text = params.get("tts_text", "").strip()

        lines = []

        # Collect video files
        video_files = []
        for key, path in files.items():
            if key.startswith("video"):
                video_files.append(path)
        if not video_files and "video_files" in files:
            vf = files["video_files"]
            video_files = [vf] if isinstance(vf, str) else vf

        # Add video files
        if video_files:
            for i, vf in enumerate(video_files):
                start = f"{i * duration}s"
                dur = f"{duration}s"
                lines.append(f"project.add_media_safe(r'{vf}', '{start}', '{dur}', track_name='VideoTrack')")
        else:
            lines.append("# 未提供视频素材，请在剪映中手动添加")

        # Add audio
        if "audio_file" in files:
            audio_path = files["audio_file"]
            total_dur = f"{len(video_files) * duration}s" if video_files else "10s"
            lines.append(f"project.add_audio_safe(r'{audio_path}', '0s', '{total_dur}', track_name='AudioTrack')")

        # Add title
        anim = animation
        lines.append("")
        lines.append(f"project.add_text_simple(")
        lines.append(f"    text={repr(title)},")
        lines.append(f'    start_time="0.3s",')
        lines.append(f'    duration="3s",')
        lines.append(f"    font_size=18.0,")
        lines.append(f"    color_rgb=(1, 1, 1),")
        lines.append(f"    transform_y=-0.5,")
        lines.append(f"    anim_in={repr(anim)},")
        lines.append(f'    track_name="TitleTrack",')
        lines.append(f")")

        # TTS placeholder
        if tts_text:
            lines.append("")
            lines.append("# TTS 配音（如需自动配音，请使用 AI 模式或手动在剪映中添加）")
            lines.append(f"# tts_text = {repr(tts_text)}")

        # Save
        lines.append("")
        lines.append("project.save()")

        return "\n".join(lines)
