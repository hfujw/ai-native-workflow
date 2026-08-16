"""chat_stream 建连重试 + token 估算兜底（客户端行为，修复 ③④）。"""
from unittest.mock import patch

import pytest

from app.llm.client import chat_stream


class _FakeChunk:
    """空 chunk：无内容、无 usage → 触发 token 估算兜底。"""
    def __init__(self):
        self.choices = []
        self.usage = None


class _FakeClient:
    """前 fail_count 次 create 抛超时，之后成功返回空流。"""
    def __init__(self, fail_count: int):
        self.calls = 0
        self.fail_count = fail_count

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    @property
    def create(self):
        async def _create(**kwargs):
            self.calls += 1
            if self.calls <= self.fail_count:
                raise TimeoutError("connection timeout")
            async def _gen():
                yield _FakeChunk()
            return _gen()
        return _create


@pytest.mark.asyncio
async def test_chat_stream_retries_connection():
    """建连瞬态失败 → 重试成功（不把半截异常抛给调用方）。"""
    client = _FakeClient(fail_count=2)  # 前两次建连都失败
    records = []
    with patch("app.llm.client._assert_configured", return_value=None), \
         patch("app.llm.client._get_client", return_value=client):
        chunks = [t async for t in chat_stream("测试", system="", model="deepseek-v4-flash", session_records=records)]
    assert client.calls == 3  # 失败2次 + 成功1次 = 重试生效
    assert chunks == []
    assert records and records[0]["model"] == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_chat_stream_fallback_token_estimate():
    """无 usage 时按字符估算记账（//2，宁可高估预算不少算）。"""
    client = _FakeClient(fail_count=0)
    records = []
    with patch("app.llm.client._assert_configured", return_value=None), \
         patch("app.llm.client._get_client", return_value=client):
        async for _ in chat_stream("测试主题", system="", model="deepseek-v4-flash", session_records=records):
            pass
    assert records[0]["input_tokens"] == 2   # len("测试主题")=4 // 2
    assert records[0]["output_tokens"] == 1  # 空流 → 至少 1
