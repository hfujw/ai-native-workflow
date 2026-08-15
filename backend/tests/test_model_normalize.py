"""模型名归一化测试——用户前端填什么名都能用（DeepSeek 官方改名兼容）。

覆盖：
- NM-1 "deepseek"（简名）→ deepseek-v4-flash
- NM-2 "deepseek-chat"（旧名）→ deepseek-v4-flash
- NM-3 "deepseek-reasoner"（旧名）→ deepseek-v4-pro
- NM-4 官方新名原样保留
- NM-5 未知模型（gpt-4o）原样透传
- NM-6 chat() 实际用归一化名请求
- NM-7 chat_json 对简名 "deepseek" 不传 json_object？——注意：deepseek 映射到 flash，
     不是推理模型，应传 json_object。is_reasoning_model("deepseek") 应为 False。
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.llm.client import is_reasoning_model, normalize_model


def test_normalize_short_name():
    assert normalize_model("deepseek") == "deepseek-v4-flash"


def test_normalize_case_variants():
    """大小写变体——用户实际传的是 deepseek-Flash（大写 F），必须映射。"""
    assert normalize_model("deepseek-Flash") == "deepseek-v4-flash"
    assert normalize_model("DeepSeek-Flash") == "deepseek-v4-flash"
    assert normalize_model("deepseek-Pro") == "deepseek-v4-pro"
    assert normalize_model("DeepSeek-Pro") == "deepseek-v4-pro"
    assert normalize_model("deepseek-pro") == "deepseek-v4-pro"


def test_normalize_old_chat_name():
    assert normalize_model("deepseek-chat") == "deepseek-v4-flash"
    assert normalize_model("deepseek-Chat") == "deepseek-v4-flash"


def test_normalize_old_reasoner_name():
    assert normalize_model("deepseek-reasoner") == "deepseek-v4-pro"
    assert normalize_model("DeepSeek-Reasoner") == "deepseek-v4-pro"


def test_normalize_official_names_pass_through():
    assert normalize_model("deepseek-v4-flash") == "deepseek-v4-flash"
    assert normalize_model("deepseek-v4-pro") == "deepseek-v4-pro"


def test_normalize_unknown_model_passthrough():
    assert normalize_model("gpt-4o") == "gpt-4o"
    assert normalize_model("claude-3-5-sonnet") == "claude-3-5-sonnet"


def test_normalize_none():
    assert normalize_model(None) is None


def test_reasoning_detection():
    assert is_reasoning_model("deepseek-reasoner")
    assert is_reasoning_model("deepseek-v4-pro")
    assert is_reasoning_model("deepseek-Pro")  # 大小写变体
    assert is_reasoning_model("DeepSeek-Reasoner")
    assert not is_reasoning_model("deepseek")
    assert not is_reasoning_model("deepseek-chat")
    assert not is_reasoning_model("deepseek-v4-flash")
    assert not is_reasoning_model("deepseek-Flash")  # 大小写变体
    assert not is_reasoning_model("gpt-4o")


@pytest.mark.asyncio
async def test_chat_uses_normalized_model():
    """chat() 用简名 deepseek → 实际请求 deepseek-v4-flash。"""
    from app.llm import client as client_mod
    from app.llm.client import bind_session_client, clear_session_client

    bind_session_client("sk-test", None)
    captured = {}

    fake_response = AsyncMock()
    fake_response.choices = [AsyncMock()]
    fake_response.choices[0].message.content = "ok"
    fake_response.usage = None

    fake_client = AsyncMock()
    fake_client.chat.completions.create = AsyncMock(return_value=fake_response)

    with patch.object(client_mod, "_get_client", return_value=fake_client):
        out = await client_mod.chat("你好", model="deepseek", session_records=[])
    assert out == "ok"
    captured_model = fake_client.chat.completions.create.call_args.kwargs.get("model")
    assert captured_model == "deepseek-v4-flash"
    clear_session_client()


@pytest.mark.asyncio
async def test_chat_normalizes_reasoner_for_request():
    """reasoner 旧名 → 请求 deepseek-v4-pro。"""
    from app.llm import client as client_mod
    from app.llm.client import bind_session_client, clear_session_client

    bind_session_client("sk-test", None)

    fake_response = AsyncMock()
    fake_response.choices = [AsyncMock()]
    fake_response.choices[0].message.content = "ok"
    fake_response.usage = None

    fake_client = AsyncMock()
    fake_client.chat.completions.create = AsyncMock(return_value=fake_response)

    with patch.object(client_mod, "_get_client", return_value=fake_client):
        await client_mod.chat("你好", model="deepseek-reasoner", session_records=[])
    captured_model = fake_client.chat.completions.create.call_args.kwargs.get("model")
    assert captured_model == "deepseek-v4-pro"
    clear_session_client()
