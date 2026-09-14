"""
ffmpeg 视频处理器
================
剪切、拼接、字幕烧录、音频提取、品描叠加。
所有操作通过 subprocess 调用 ffmpeg/ffprobe。
"""

import subprocess
import json
import os
from pathlib import Path
from typing import List, Optional


class VideoProcessor:
    def __init__(self, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe"):
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe

    # ── 元数据 ──

    def get_info(self, path: str) -> dict:
        """获取视频元数据"""
        cmd = [
            self.ffprobe, "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(f"ffprobe 失败: {r.stderr}")

        data = json.loads(r.stdout)
        info = {"duration": float(data.get("format", {}).get("duration", 0))}
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                info["width"] = stream.get("width", 0)
                info["height"] = stream.get("height", 0)
                info["orientation"] = "vertical" if info["height"] > info["width"] else "horizontal"
                info["fps"] = eval(stream.get("r_frame_rate", "0/1"))
                info["codec"] = stream.get("codec_name", "")
                break
        return info

    def get_duration(self, path: str) -> float:
        return self.get_info(path).get("duration", 0)

    # ── 音频提取 ──

    def extract_audio(self, video_path: str, output_path: str,
                       sample_rate: int = 16000, channels: int = 1) -> str:
        """从视频提取音频（用于 ASR）"""
        cmd = [
            self.ffmpeg, "-y", "-i", str(video_path),
            "-vn", "-acodec", "pcm_s16le",
            "-ar", str(sample_rate), "-ac", str(channels),
            str(output_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(f"音频提取失败: {r.stderr[:500]}")
        return output_path

    # ── 视频剪切 ──

    def cut_segment(self, input_path: str, start: float, duration: float,
                    output_path: str, reencode: bool = True) -> str:
        """
        精确剪切视频片段。
        reencode=True 确保关键帧精确对齐（慢但准确）。
        """
        if reencode:
            cmd = [
                self.ffmpeg, "-y",
                "-ss", str(start), "-i", str(input_path),
                "-t", str(duration),
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-avoid_negative_ts", "1",
                str(output_path),
            ]
        else:
            cmd = [
                self.ffmpeg, "-y",
                "-ss", str(start), "-i", str(input_path),
                "-t", str(duration),
                "-c", "copy",
                "-avoid_negative_ts", "1",
                str(output_path),
            ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f"视频剪切失败: {r.stderr[:500]}")
        return output_path

    # ── 视频拼接 ──

    def concat_segments(self, segment_paths: List[str],
                         output_path: str) -> str:
        """拼接多个视频片段（concat demuxer）"""
        # 先确保所有片段的编码一致，否则 concat 会出问题
        list_path = Path(output_path).with_suffix(".list.txt")

        with open(list_path, "w", encoding="utf-8") as f:
            for p in segment_paths:
                f.write(f"file '{os.path.abspath(p)}'\n")

        cmd = [
            self.ffmpeg, "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_path),
            "-c", "copy",
            str(output_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        # Clean up list file
        try:
            os.remove(list_path)
        except:
            pass

        if r.returncode != 0:
            # Re-encode fallback (if codecs differ)
            return self._concat_with_reencode(segment_paths, output_path)

        return output_path

    def _concat_with_reencode(self, segment_paths: List[str],
                               output_path: str) -> str:
        """拼接并重新编码（处理编码不一致的情况）"""
        # Build complex filter: [0:v][0:a][1:v][1:a]...
        inputs = []
        filter_parts = []
        for i, p in enumerate(segment_paths):
            inputs.extend(["-i", str(p)])
            filter_parts.append(f"[{i}:v][{i}:a]")

        filter_str = "".join(filter_parts) + f"concat=n={len(segment_paths)}:v=1:a=1[outv][outa]"

        cmd = [
            self.ffmpeg, "-y", *inputs,
            "-filter_complex", filter_str,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError(f"视频拼接失败: {r.stderr[:500]}")
        return output_path

    # ── 字幕烧录 ──

    def burn_subtitles(self, input_path: str, srt_path: str,
                        output_path: str,
                        font_name: str = "Microsoft YaHei",
                        font_size: int = 24,
                        font_color: str = "&H00FFFFFF",
                        outline_color: str = "&H80000000",
                        outline_width: int = 2,
                        alignment: int = 2,
                        margin_v: int = 40,
                        shadow: int = 0,
                        bold: str = "0",
                        italic: str = "0",
                        border_style: int = 1,
                        ) -> str:
        """
        硬字幕烧录（ffmpeg subtitles filter）。
        支持 ASS 格式的所有样式参数。
        font_color 和 outline_color 是 ASS 颜色格式: &HAABBGGRR
        alignment: 1左下 2底部居中 3右下 5左上 6顶部居中 7右上 9居中
        border_style: 1=描边+阴影 3=背景框
        """
        srt_escaped = str(srt_path).replace("\\", "/").replace(":", "\\:")

        style = (
            f"FontName={font_name},"
            f"FontSize={font_size},"
            f"PrimaryColour={font_color},"
            f"OutlineColour={outline_color},"
            f"Outline={outline_width},"
            f"Alignment={alignment},"
            f"MarginV={margin_v},"
            f"Shadow={shadow},"
            f"Bold={bold},"
            f"Italic={italic},"
            f"BorderStyle={border_style}"
        )

        cmd = [
            self.ffmpeg, "-y", "-i", str(input_path),
            "-vf", f"subtitles='{srt_escaped}':force_style='{style}'",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "copy",
            str(output_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError(f"字幕烧录失败: {r.stderr[:500]}")
        return output_path

    # ── 品描文字叠加 ──

    def _find_font(self) -> str:
        """Find an available Chinese font on the system"""
        import platform
        candidates = []
        if platform.system() == "Windows":
            candidates = [
                "C:/Windows/Fonts/msyh.ttc",
                "C:/Windows/Fonts/simhei.ttf",
                "C:/Windows/Fonts/simsun.ttc",
            ]
        elif platform.system() == "Darwin":
            candidates = [
                "/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/STHeiti Light.ttc",
            ]
        else:
            candidates = [
                "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            ]
        for c in candidates:
            if Path(c).exists():
                return c
        return candidates[0]  # Last resort

    def add_overlay_text(self, input_path: str, overlay_texts: List[dict],
                          output_path: str,
                          fontfile: str = "") -> str:
        """
        叠加品描文本到视频。
        overlay_texts: [{text, position, font_size, font_color, start_time, end_time}, ...]
        position: top-left | top-right | bottom-left | bottom-right | center
        """
        # Auto-detect font
        if not fontfile:
            fontfile = self._find_font()
        font_escaped = fontfile.replace("\\", "/").replace(":", "\\:")

        # Build drawtext filters
        filters = []
        for ov in overlay_texts:
            text = ov["text"].replace(":", "\\:").replace("'", "\\'").replace("%", "\\%")
            pos = ov.get("position", "top-right")
            fs = ov.get("font_size", 20)
            fc = ov.get("font_color", "white")
            bw = ov.get("border_width", 1)
            bc = ov.get("border_color", "black@0.6")
            start_t = ov.get("start_time", 0)
            end_t = ov.get("end_time", 99999)

            pos_map = {
                "top-left": "x=20:y=20",
                "top-right": "x=w-tw-20:y=20",
                "bottom-left": "x=20:y=h-th-20",
                "bottom-right": "x=w-tw-20:y=h-th-20",
                "center": "x=(w-tw)/2:y=(h-th)/2",
            }
            xy = pos_map.get(pos, "x=w-tw-20:y=20")

            enable = ""
            if start_t > 0 or end_t < 99999:
                enable = f":enable='between(t,{start_t},{end_t})'"

            filters.append(
                f"drawtext=text='{text}':{xy}:fontsize={fs}:fontcolor={fc}"
                f":fontfile='{font_escaped}':borderw={bw}:bordercolor={bc}{enable}"
            )

        vf = ",".join(filters)

        cmd = [
            self.ffmpeg, "-y", "-i", str(input_path),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "copy",
            str(output_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError(f"品描叠加失败: {r.stderr[:500]}")
        return output_path

    # ── 混合配音 ──

    def mix_audio(self, video_path: str, audio_path: str,
                   output_path: str, audio_volume: float = 0.8) -> str:
        """将外部配音混入视频"""
        cmd = [
            self.ffmpeg, "-y",
            "-i", str(video_path), "-i", str(audio_path),
            "-filter_complex",
            f"[1:a]volume={audio_volume}[a1];[0:a][a1]amix=inputs=2:duration=first:dropout_transition=2",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            str(output_path),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError(f"音频混合失败: {r.stderr[:500]}")
        return output_path
