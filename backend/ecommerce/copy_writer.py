"""
AI 电商文案生成器
================
复用现有的 LLM 代理架构，使用专门的电商 system prompt。
"""

import json
import os
import httpx
from typing import List, Optional

# Provider 配置（与 main.py 保持一致）
PROVIDER_CONFIG = {
    "deepseek": {
        "url": "https://api.deepseek.com/chat/completions",
        "default_model": "deepseek-v4-flash",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
    "mimo": {
        "url": "https://token-plan-cn.xiaomimomo.com/v1/chat/completions",
        "default_model": "mimo-v2.5-pro",
        "auth_header": "api-key",
        "auth_prefix": "",
    },
    "qwen": {
        "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "default_model": "qwen3.6-flash",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
}

# ── 电商专用 System Prompts ──

VOICEOVER_ARRANGE_PROMPT = """你是一个短视频电商文案专家。根据用户提供的口播文案（SRT字幕内容），分析哪些是"爆款句子"，然后生成 3 套不同的视频片段排列方案。

每条文案你需要：
1. 识别最吸引人的句子（钩子、痛点、卖点、转化引导）
2. 设计不同的排列顺序（不同的开头钩子 → 不同的节奏感）

输出 JSON 格式：
```json
{
  "plans": [
    {
      "plan_name": "方案名称（如：痛点前置型）",
      "style": "风格描述",
      "arrangement": {
        "order": [0, 2, 1, 3],
        "repeats": {"0": 2},
        "drop": [],
        "highlights": {}
      },
      "new_subtitles": [
        {"index": 0, "text": "修改后的字幕文本（可微调原文）"}
      ]
    }
  ]
}
```

字段说明：
- order: 片段索引的排列顺序（从0开始）
- repeats: {"片段索引": 重复次数}，空对象{}表示不重复
- drop: 要丢弃的片段索引列表
- highlights: {"片段索引": {"start": 0.5, "duration": 2.0}}，对片段内精剪
- new_subtitles: 可选，对字幕文本的微调

只输出 JSON，不要其他文字。"""


NO_VOICEOVER_COPY_PROMPT = """你是一个短视频好物种草文案专家。根据用户提供的产品信息，生成适合作为视频字幕的种草文案。

要求：
- 每行 8-15 字，适合竖屏短视频
- 前 3 行是吸引注意力的钩子
- 突出产品卖点和使用场景
- 加入紧迫感或社交证明
- 输出 JSON 数组格式

输出格式：
```json
{
  "plans": [
    {
      "plan_name": "风格名称",
      "style": "捡漏型 / 效果型 / 场景型 / 对比型",
      "lines": [
        {"text": "这价格真的绝了", "display_duration": 2.0},
        {"text": "同事都问我链接", "display_duration": 2.5},
        {"text": "限时特惠 ¥99", "display_duration": 3.0}
      ],
      "tts_speaker": "zh_female_xiaopengyou"
    }
  ]
}
```

只输出 JSON，不要其他文字。"""


PRODUCT_OVERLAY_PROMPT = """根据产品信息生成视频角落的品描叠加文字。

输出 JSON 数组：
```json
[
  {"text": "限时特惠 ¥99", "position": "top-right", "font_size": 18},
  {"text": "已售 10万+", "position": "top-left", "font_size": 16}
]
```

位置可选: top-left, top-right, bottom-left, bottom-right, center
每行 4-10 字。只输出 JSON 数组。"""


class CopyWriter:
    """AI 电商文案生成器"""

    def __init__(self, provider: str = "deepseek", model: str = None, api_key: str = None):
        self.provider = provider
        cfg = PROVIDER_CONFIG.get(provider, PROVIDER_CONFIG["deepseek"])
        self.model = model or cfg["default_model"]
        self.api_url = cfg["url"]
        self.auth_header = cfg["auth_header"]
        self.auth_prefix = cfg["auth_prefix"]
        self.api_key = api_key or os.environ.get(f"{provider.upper()}_API_KEY", "")

    async def _call_llm(self, system_prompt: str, user_input: str,
                         temperature: float = 0.8, max_tokens: int = 4096) -> str:
        """内部调用 LLM"""
        headers = {
            "Content-Type": "application/json",
            self.auth_header: f"{self.auth_prefix}{self.api_key}",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(self.api_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def generate_voiceover_plans(self, subtitle_text: str,
                                        product_info: str = "",
                                        count: int = 3) -> dict:
        """生成口播视频的排列方案"""
        user_input = f"口播文案内容：\n{subtitle_text}\n"
        if product_info:
            user_input += f"\n产品信息：\n{product_info}\n"
        user_input += f"\n请生成 {count} 套排列方案。"

        result = await self._call_llm(VOICEOVER_ARRANGE_PROMPT, user_input)
        return self._parse_json_response(result)

    async def generate_no_voiceover_copy(self, product_info: str,
                                          count: int = 3) -> dict:
        """生成无口播视频的种草文案"""
        user_input = f"产品信息：\n{product_info}\n\n请生成 {count} 套种草文案方案。"
        result = await self._call_llm(NO_VOICEOVER_COPY_PROMPT, user_input)
        return self._parse_json_response(result)

    async def generate_overlay_texts(self, product_info: str) -> list:
        """生成品描叠加文字"""
        user_input = f"产品信息：\n{product_info}"
        result = await self._call_llm(PRODUCT_OVERLAY_PROMPT, user_input)
        return self._parse_json_response(result)

    def _parse_json_response(self, text: str):
        """解析 LLM 输出的 JSON"""
        text = text.strip()
        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:] if lines[0].startswith("```") else lines
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON block
            import re
            m = re.search(r'\{[\s\S]*\}', text)
            if m:
                return json.loads(m.group())
            m = re.search(r'\[[\s\S]*\]', text)
            if m:
                return json.loads(m.group())
            raise ValueError(f"无法解析 LLM 输出为 JSON: {text[:200]}")
