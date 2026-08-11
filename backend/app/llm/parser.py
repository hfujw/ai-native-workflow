"""LLM 输出解析 — markdown 围栏清洗、thought 防御、JSON 校验等纯函数。

这些函数不依赖网络、不依赖配置，可独立测试。
"""

import json
import re


def strip_fence(text: str) -> str:
    """去掉 LLM 响应中的 markdown 代码围栏。

    支持 ```json、```html、```python 等任意语言标记。
    """
    text = text.strip()
    text = re.sub(r'^```[a-zA-Z]*\s*\n?', '', text)   # 开头 fence
    text = re.sub(r'\n?```\s*$', '', text)              # 结尾 fence
    return text.strip()


def clean_thought(thought: str, user_input: str, step: int) -> str:
    """清洗 LLM 思考内容：截断重复开场白，保留实质部分。

    第 2 步及以后，LLM 容易重复"用户想了解XXX""我对XXX不太熟悉"等开场白。
    检测这些冗余模式，截断到第一个实质判断句。
    """
    if step <= 0:
        return thought

    redundant_patterns = [
        f"想了解{user_input}",
        f"对{user_input}这个名字",
        "我不确定他是谁",
        "我不确定具体是谁",
        "我对这个人没有太多",
    ]
    for pattern in redundant_patterns:
        if pattern in thought[:80]:
            # 找第一个实质标记，截断前面冗余部分
            for marker in ["因此", "所以", "我决定", "接下来", "现在", "基于",
                          "上一步", "搜索", "素材"]:
                idx = thought.find(marker, 20)
                if 0 < idx < 120:
                    return thought[idx:]
            break
    return thought


def safe_parse_json(text: str) -> dict | None:
    """解析 LLM JSON 输出；失败或非 dict 时返回 None（调用方决定降级策略）。"""
    try:
        result = json.loads(strip_fence(text))
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, TypeError):
        pass
    return None


# 注入检测——搜索/外部内容里常见的提示注入特征
_INJECTION_PATTERNS = [
    "ignore all previous", "ignore previous", "ignore instructions",
    "忽略之前的", "忽略前面", "忽略以上", "system prompt", "system message",
    "你是一个", "you are now", "act as", "不要输出", "don't output",
]


def detect_injection(text: str) -> list[str]:
    """检测文本中是否含提示注入特征。返回命中的特征列表，空 = 安全。"""
    lowered = (text or "").lower()
    return [p for p in _INJECTION_PATTERNS if p.lower() in lowered]
