"""
视频片段排列引擎
================
根据 AI 生成的排列方案，重组视频片段并拼接。
"""

import os
import uuid
from pathlib import Path
from typing import List, Optional
from .video_processor import VideoProcessor
from .srt_handler import SrtSegment, write_srt


class SegmentArranger:
    """视频片段排列引擎"""

    def __init__(self, video_processor: VideoProcessor = None):
        self.vp = video_processor or VideoProcessor()
        self.work_dir: Optional[Path] = None

    def set_work_dir(self, path: Path):
        self.work_dir = path
        path.mkdir(parents=True, exist_ok=True)

    # ── 按字幕切段 ──

    def cut_by_segments(self, video_path: str,
                         segments: List[SrtSegment]) -> List[str]:
        """按 SRT 字幕时间戳切割视频"""
        paths = []
        for i, seg in enumerate(segments):
            out = str(self.work_dir / f"seg_{i:04d}.mp4")
            self.vp.cut_segment(video_path, seg.start, seg.duration, out)
            paths.append(out)
        return paths

    def cut_by_cut_points(self, video_path: str,
                           cut_points: List[dict]) -> List[str]:
        """按切割点切视频"""
        paths = []
        for i, cp in enumerate(cut_points):
            out = str(self.work_dir / f"seg_{i:04d}.mp4")
            self.vp.cut_segment(video_path, cp["start"],
                                 cp["end"] - cp["start"], out)
            paths.append(out)
        return paths

    # ── 按方案排列 ──

    def arrange(self, segment_paths: List[str],
                plan: dict) -> str:
        """
        按 AI 方案重排并拼接片段。

        plan = {
            "order": [2, 0, 1, 3],
            "repeats": {"0": 2},
            "drop": [4],
            "highlights": {"2": {"start": 0.5, "duration": 2.0}}
        }
        """
        order = plan.get("order", list(range(len(segment_paths))))
        repeats = plan.get("repeats", {})
        drop = set(plan.get("drop", []))
        highlights = plan.get("highlights", {})

        ordered = []
        for idx in order:
            if idx in drop or idx >= len(segment_paths):
                continue

            path = segment_paths[idx]
            repeat_count = repeats.get(str(idx), 1)

            for r in range(repeat_count):
                key = str(idx)
                if key in highlights and r == 0:
                    # 对第一次出现的片段做精剪
                    h = highlights[key]
                    hl_path = str(self.work_dir / f"seg_{idx:04d}_hl.mp4")
                    self.vp.cut_segment(path, h.get("start", 0),
                                         h.get("duration", 3.0), hl_path)
                    ordered.append(hl_path)
                else:
                    ordered.append(path)

        output = str(self.work_dir / "arranged.mp4")
        return self.vp.concat_segments(ordered, output)

    # ── 字幕生成与烧录 ──

    def generate_srt_for_arrangement(self, original_segments: List[SrtSegment],
                                      plan: dict,
                                      output_path: str) -> List[SrtSegment]:
        """
        为排列后的视频生成新的 SRT 字幕。
        根据排列顺序重新计算时间戳。
        """
        order = plan.get("order", list(range(len(original_segments))))
        repeats = plan.get("repeats", {})
        drop = set(plan.get("drop", []))

        new_segments = []
        cursor = 0.0
        index = 1

        for idx in order:
            if idx in drop or idx >= len(original_segments):
                continue
            seg = original_segments[idx]
            repeat_count = repeats.get(str(idx), 1)

            for _ in range(repeat_count):
                new_segments.append(SrtSegment(
                    index=index,
                    start=cursor,
                    end=cursor + seg.duration,
                    text=seg.text,
                ))
                cursor += seg.duration
                index += 1

        # 如果有自定义字幕文本，应用替换
        new_subtitles = plan.get("new_subtitles", [])
        for ns in new_subtitles:
            nidx = ns.get("index", -1)
            if 0 <= nidx < len(new_segments):
                new_segments[nidx].text = ns.get("text", new_segments[nidx].text)

        write_srt(new_segments, output_path)
        return new_segments

    def process_pipeline(self, video_path: str,
                          original_segments: List[SrtSegment],
                          plan: dict,
                          subtitle_style: dict = None,
                          overlay_texts: list = None) -> dict:
        """
        完整管线：切段 → 排列 → 拼接 → 字幕 → 品描。
        返回 {video_path, srt_path, segments_count}
        """
        style = subtitle_style or {}

        # 1. 切段
        seg_paths = self.cut_by_segments(video_path, original_segments)

        # 2. 排列拼接
        arranged = self.arrange(seg_paths, plan)

        # 3. 生成新 SRT
        srt_path = str(self.work_dir / "output.srt")
        new_segs = self.generate_srt_for_arrangement(
            original_segments, plan, srt_path)

        # 4. 烧录字幕
        with_subtitles = str(self.work_dir / "with_subtitles.mp4")
        self.vp.burn_subtitles(
            arranged, srt_path, with_subtitles,
            font_name=style.get("font_name", "Microsoft YaHei"),
            font_size=style.get("font_size", 24),
            font_color=style.get("font_color", "&H00FFFFFF"),
            outline_color=style.get("outline_color", "&H80000000"),
            outline_width=style.get("outline_width", 2),
        )

        # 5. 品描叠加
        final = with_subtitles
        if overlay_texts:
            final = str(self.work_dir / "final.mp4")
            self.vp.add_overlay_text(with_subtitles, overlay_texts, final)

        return {
            "video_path": final,
            "srt_path": srt_path,
            "segments_count": len(new_segs),
            "duration": new_segs[-1].end if new_segs else 0,
        }
