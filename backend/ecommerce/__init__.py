"""
电商混剪模块
==========
提供 ASR 转写、视频处理、SRT 字幕、AI 文案、片段排列等能力。
"""

from .srt_handler import (
    SrtSegment, parse_srt, parse_srt_content, write_srt,
    segments_from_text, cut_points_from_segments,
    shift_segments, segments_to_text, parse_srt_time,
)
from .video_processor import VideoProcessor
