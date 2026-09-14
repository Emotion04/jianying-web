"""
插拔式 ASR 引擎
===============
支持阿里云、本地 Whisper、自定义 HTTP 回调。
"""

import os
import json
import time
import hashlib
import hmac
import base64
import uuid
from abc import ABC, abstractmethod
from typing import List
from dataclasses import dataclass

import httpx


@dataclass
class AsrSegment:
    """ASR 识别结果段"""
    start: float    # 秒
    end: float
    text: str


class AsrEngine(ABC):
    """ASR 引擎抽象基类"""

    @abstractmethod
    async def transcribe(self, audio_path: str, **kwargs) -> List[AsrSegment]:
        """转写音频文件，返回带时间戳的文本段"""
        ...


# ═══════════════════════════════════════════════════════════
# 阿里云 ASR 引擎（推荐主路径）
# ═══════════════════════════════════════════════════════════

class AliyunAsrEngine(AsrEngine):
    """
    阿里云录音文件识别 API (RESTful)。

    需要: app_key, access_key_id, access_key_secret
    文档: https://help.aliyun.com/document_detail/90771.html
    """

    BASE_URL = "https://nls-gateway-cn-shanghai.aliyuncs.com/rest/v1"

    def __init__(self, app_key: str, access_key_id: str, access_key_secret: str):
        self.app_key = app_key
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret

    async def transcribe(self, audio_path: str, **kwargs) -> List[AsrSegment]:
        """阿里云录音文件识别"""

        # 1. 上传音频获取 task_id
        task_id = await self._submit_task(audio_path)

        # 2. 轮询结果
        result = await self._poll_result(task_id)

        # 3. 解析为 AsrSegment
        return self._parse_result(result)

    async def _submit_task(self, audio_path: str) -> str:
        """提交识别任务"""
        uri = "/api/v1/asr/rest/rec"
        url = f"https://nls-gateway-cn-shanghai.aliyuncs.com{uri}"

        with open(audio_path, "rb") as f:
            audio_content = base64.b64encode(f.read()).decode()

        body = {
            "app_key": self.app_key,
            "audio_content": audio_content,
            "format": "wav",
            "sample_rate": 16000,
            "enable_words": True,
            "enable_timestamp": True,
            "max_single_segment_time": 5000,  # 最长单句 5s
        }

        headers = self._sign("POST", uri, body)

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != 20000000:
                raise RuntimeError(f"阿里云 ASR 提交失败: {data.get('status_text', data)}")
            return data["result"]["task_id"]

    async def _poll_result(self, task_id: str, max_wait: int = 600) -> dict:
        """轮询识别结果"""
        uri = f"/api/v1/asr/rest/rec/{task_id}"
        url = f"https://nls-gateway-cn-shanghai.aliyuncs.com{uri}"

        headers = self._sign("GET", uri)

        for _ in range(max_wait // 2):
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()

                status = data.get("status")
                if status == 21050000:  # 识别完成
                    return data["result"]
                elif status == 21050002:  # 识别中
                    await asyncio_sleep(3)
                    continue
                else:
                    raise RuntimeError(f"ASR 识别失败: {data.get('status_text', data)}")

        raise TimeoutError(f"ASR 识别超时 ({max_wait}s)")

    def _parse_result(self, result: dict) -> List[AsrSegment]:
        """解析阿里云返回结果为 AsrSegment 列表"""
        segments = []
        sentences = result.get("sentences", [])
        for sent in sentences:
            words = sent.get("words", [])
            if words:
                start = words[0].get("start_time", 0)
                end = words[-1].get("end_time", 0)
            else:
                start = sent.get("begin_time", 0)
                end = sent.get("end_time", 0)

            segments.append(AsrSegment(
                start=start / 1000.0,  # 毫秒转秒
                end=end / 1000.0,
                text=sent.get("text", ""),
            ))

        return segments

    def _sign(self, method: str, uri: str, body: dict = None) -> dict:
        """阿里云 V1 签名"""
        import urllib.parse
        from datetime import datetime, timezone, timedelta

        tz = timezone(timedelta(hours=8))
        now = datetime.now(tz)

        # 构建签名字符串
        body_md5 = base64.b64encode(
            hashlib.md5(json.dumps(body or {}).encode()).digest()
        ).decode()

        headers_to_sign = {
            "Content-Type": "application/json",
            "Date": now.strftime("%a, %d %b %Y %H:%M:%S GMT"),
            "X-NLS-RequestId": str(uuid.uuid4()),
        }

        string_to_sign = f"{method}\napplication/json\n{body_md5}\napplication/json\n{headers_to_sign['Date']}\nx-nls-requestid:{headers_to_sign['X-NLS-RequestId']}\n{uri}"

        signature = base64.b64encode(
            hmac.new(
                self.access_key_secret.encode(),
                string_to_sign.encode(),
                hashlib.sha1,
            ).digest()
        ).decode()

        return {
            **headers_to_sign,
            "Authorization": f"Dataplus {self.access_key_id}:{signature}",
        }


# ═══════════════════════════════════════════════════════════
# 自定义 HTTP ASR（用户自有服务）
# ═══════════════════════════════════════════════════════════

class HttpCallbackAsrEngine(AsrEngine):
    """自定义 HTTP ASR 回调"""

    def __init__(self, endpoint: str, api_key: str = ""):
        self.endpoint = endpoint
        self.api_key = api_key

    async def transcribe(self, audio_path: str, **kwargs) -> List[AsrSegment]:
        headers = {"Content-Type": "application/octet-stream"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        with open(audio_path, "rb") as f:
            content = f.read()

        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(self.endpoint, content=content, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        # 期望返回: [{"start": 0.0, "end": 2.5, "text": "..."}, ...]
        return [AsrSegment(**item) for item in data]


# ═══════════════════════════════════════════════════════════
# 本地 Whisper ASR（推荐：免费、离线、高准确率）
# ═══════════════════════════════════════════════════════════

class WhisperAsrEngine(AsrEngine):
    """
    本地 Whisper 引擎。
    优先使用 faster-whisper，回退到 openai-whisper。

    安装: pip install faster-whisper
    模型自动下载到系统缓存目录。
    """

    def __init__(self, model_size: str = "base", device: str = "cpu",
                  compute_type: str = "int8"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def _get_model(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(
                self.model_size, device=self.device, compute_type=self.compute_type)
            return self._model
        except ImportError:
            pass
        try:
            import whisper
            self._model = whisper.load_model(self.model_size)
            return self._model
        except ImportError:
            raise ImportError(
                "请安装语音识别库: pip install faster-whisper  (推荐) "
                "或 pip install openai-whisper")

    async def transcribe(self, audio_path: str, **kwargs) -> List[AsrSegment]:
        """转写音频，返回带时间戳的文本段"""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._transcribe_sync, audio_path)

    def _convert_to_simplified(self, text: str) -> str:
        """繁→简转换"""
        try:
            from opencc import OpenCC
            cc = OpenCC('t2s')  # Traditional to Simplified
            return cc.convert(text)
        except ImportError:
            return text

    def _transcribe_sync(self, audio_path: str) -> List[AsrSegment]:
        model = self._get_model()
        segments = []

        # faster-whisper
        if hasattr(model, 'transcribe') and not isinstance(model, type):
            segs, info = model.transcribe(audio_path, beam_size=5,
                                           vad_filter=True,
                                           vad_parameters=dict(
                                               min_silence_duration_ms=500,
                                               threshold=0.5,
                                               speech_pad_ms=200,
                                           ),
                                           language="zh",
                                           initial_prompt="以下是简体中文普通话的句子。每句都是完整的语义单元。",
                                           word_timestamps=False)
            for seg in segs:
                text = seg.text.strip()
                if not text: continue
                dur = seg.end - seg.start
                # Skip only extremely short noise (< 0.3s)
                if dur < 0.3: continue
                text = self._convert_to_simplified(text)
                segments.append(AsrSegment(
                    start=seg.start, end=seg.end, text=text))

        # openai-whisper
        elif hasattr(model, 'transcribe'):
            result = model.transcribe(audio_path, language="zh",
                                       word_timestamps=True,
                                       initial_prompt="以下是简体中文普通话。")
            for seg in result.get("segments", []):
                dur = seg["end"] - seg["start"]
                words = len(seg.get("text", "").strip())
                if dur > 0 and words / max(dur, 0.5) < 1.0 and dur < 2.0:
                    continue
                text = self._convert_to_simplified(seg["text"].strip())
                segments.append(AsrSegment(
                    start=seg["start"], end=seg["end"],
                    text=text))

        return segments


# ═══════════════════════════════════════════════════════════
# 工厂函数
# ═══════════════════════════════════════════════════════════

def create_asr_engine(config: dict) -> AsrEngine:
    """根据配置创建 ASR 引擎"""
    engine_type = config.get("asr_engine", "whisper")

    if engine_type == "aliyun":
        return AliyunAsrEngine(
            app_key=config.get("aliyun_asr_app_key", os.environ.get("ALIYUN_ASR_APP_KEY", "")),
            access_key_id=config.get("aliyun_asr_access_key_id", os.environ.get("ALIYUN_ASR_ACCESS_KEY_ID", "")),
            access_key_secret=config.get("aliyun_asr_access_key_secret", os.environ.get("ALIYUN_ASR_ACCESS_KEY_SECRET", "")),
        )
    elif engine_type == "whisper":
        return WhisperAsrEngine(
            model_size=config.get("whisper_model", "base"),
            device=config.get("whisper_device", "cpu"),
            compute_type=config.get("whisper_compute", "int8"),
        )
    elif engine_type == "http":
        return HttpCallbackAsrEngine(
            endpoint=config.get("asr_endpoint", ""),
            api_key=config.get("asr_api_key", ""),
        )
    else:
        raise ValueError(f"不支持的 ASR 引擎: {engine_type}")


# Python 3.7+ asyncio compat
import asyncio
def asyncio_sleep(seconds):
    return asyncio.sleep(seconds)
