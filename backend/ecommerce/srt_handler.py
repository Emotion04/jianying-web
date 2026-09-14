"""
SRT 字幕处理模块
===============
解析 SRT 文件、写入 SRT 文件、时间线操作。
复用 jianying-editor 的 format_srt_time() 函数。
"""

import re
import sys
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, field

# 引用 jianying-editor 的格式化工具
SKILL_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "skills" / "jianying-editor" / "scripts"
if str(SKILL_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SKILL_SCRIPTS))

from utils.formatters import format_srt_time


@dataclass
class SrtSegment:
    """单条字幕段"""
    index: int
    start: float   # 秒
    end: float     # 秒
    text: str

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def start_srt(self) -> str:
        """返回 SRT 格式的开始时间 H:MM:SS,mmm"""
        return format_srt_time(int(self.start * 1_000_000))

    @property
    def end_srt(self) -> str:
        """返回 SRT 格式的结束时间"""
        return format_srt_time(int(self.end * 1_000_000))

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "start": self.start,
            "end": self.end,
            "duration": self.duration,
            "text": self.text,
            "start_srt": self.start_srt,
            "end_srt": self.end_srt,
        }


def parse_srt_time(time_str: str) -> float:
    """解析 SRT 时间戳 H:MM:SS,mmm 或 HH:MM:SS,mmm 转为秒"""
    # Supports both formats: H:MM:SS,mmm and HH:MM:SS,mmm
    m = re.match(r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{3})', time_str.strip())
    if not m:
        raise ValueError(f"无效的 SRT 时间戳: {time_str}")
    h, mi, s, ms = int(m[1]), int(m[2]), int(m[3]), int(m[4])
    return h * 3600.0 + mi * 60.0 + s + ms / 1000.0


def parse_srt(file_path: str) -> List[SrtSegment]:
    """解析 SRT 文件，返回字幕段列表"""
    content = Path(file_path).read_text(encoding="utf-8")
    return parse_srt_content(content)


def parse_srt_content(content: str) -> List[SrtSegment]:
    """解析 SRT 文本内容"""
    segments = []
    # Normalize line endings
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    blocks = content.strip().split('\n\n')

    for block in blocks:
        lines = [l.strip() for l in block.strip().split('\n') if l.strip()]
        if len(lines) < 3:
            continue

        try:
            index = int(lines[0])
        except ValueError:
            continue

        # Parse timestamp line: "00:00:01,000 --> 00:00:03,500"
        time_match = re.match(
            r'(\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{3})',
            lines[1]
        )
        if not time_match:
            continue

        start = parse_srt_time(time_match[1])
        end = parse_srt_time(time_match[2])
        text = '\n'.join(lines[2:])

        segments.append(SrtSegment(index=index, start=start, end=end, text=text))

    return segments


def write_srt(segments: List[SrtSegment], output_path: str):
    """将字幕段列表写入 SRT 文件"""
    with open(output_path, 'w', encoding='utf-8') as f:
        for i, seg in enumerate(segments, 1):
            f.write(f"{i}\n")
            f.write(f"{seg.start_srt} --> {seg.end_srt}\n")
            f.write(f"{seg.text}\n\n")


def segments_from_text(text: str, duration_per_line: float = 3.0) -> List[SrtSegment]:
    """
    从纯文本生成字幕段列表（无时间戳时使用）。
    按换行或句号拆分，每行分配均等时长。
    """
    # Split by newlines and Chinese punctuation
    lines = re.split(r'[\n\r]+|[。！？]', text)
    lines = [l.strip() for l in lines if l.strip()]

    segments = []
    cursor = 0.0
    for i, line in enumerate(lines, 1):
        segments.append(SrtSegment(
            index=i,
            start=cursor,
            end=cursor + duration_per_line,
            text=line,
        ))
        cursor += duration_per_line

    return segments


def cut_points_from_segments(segments: List[SrtSegment],
                              merge_gap: float = 0.5) -> List[dict]:
    """
    将字幕段转换为视频切割点。
    相邻段间隔小于 merge_gap 时合并为一个切割区间。

    返回: [{start, end, segments: [SrtSegment], text_combined: str}, ...]
    """
    if not segments:
        return []

    sorted_segs = sorted(segments, key=lambda s: s.start)
    cuts = []
    current = {
        "start": sorted_segs[0].start,
        "end": sorted_segs[0].end,
        "segments": [sorted_segs[0]],
        "text_combined": sorted_segs[0].text,
    }

    for seg in sorted_segs[1:]:
        gap = seg.start - current["end"]
        if gap <= merge_gap:
            # Merge
            current["end"] = max(current["end"], seg.end)
            current["segments"].append(seg)
            current["text_combined"] += " " + seg.text
        else:
            cuts.append(current)
            current = {
                "start": seg.start,
                "end": seg.end,
                "segments": [seg],
                "text_combined": seg.text,
            }

    cuts.append(current)
    return cuts


def shift_segments(segments: List[SrtSegment], offset_seconds: float) -> List[SrtSegment]:
    """整体偏移字幕时间"""
    return [
        SrtSegment(
            index=s.index,
            start=max(0, s.start + offset_seconds),
            end=max(s.duration, s.end + offset_seconds),
            text=s.text,
        )
        for s in segments
    ]


def segments_to_text(segments: List[SrtSegment]) -> str:
    """提取字幕段中的纯文本（用于 AI 分析）"""
    return " ".join(s.text for s in segments)
