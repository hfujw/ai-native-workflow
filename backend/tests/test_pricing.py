"""定价体系测试：按模型计费 + 未知模型兜底 + 账本汇总。"""

from app.llm.pricing import compute_cost, get_price


def test_get_price_known_model():
    p = get_price("deepseek-chat")
    assert p["output"] == 2.0


def test_get_price_unknown_model_falls_back():
    p = get_price("gpt-4o")  # 未知模型
    assert p == get_price(None)  # 与缺省同价（兜底）


def test_compute_cost_respects_model():
    # deepseek-chat：100 万输出 token → ¥2
    records = [{"model": "deepseek-chat", "input_tokens": 0, "output_tokens": 1_000_000, "cache_hit_tokens": 0}]
    assert compute_cost(records) == 2.0

    # deepseek-reasoner：同样输出 → 更贵（费率表不同）
    records2 = [{"model": "deepseek-reasoner", "input_tokens": 0, "output_tokens": 1_000_000, "cache_hit_tokens": 0}]
    assert compute_cost(records2) > 2.0


def test_compute_cost_mixed_models():
    records = [
        {"model": "deepseek-chat", "input_tokens": 0, "output_tokens": 1_000_000, "cache_hit_tokens": 0},
        {"model": "gpt-4o", "input_tokens": 0, "output_tokens": 1_000_000, "cache_hit_tokens": 0},
    ]
    cost = compute_cost(records)
    assert cost == 2.0 + get_price(None)["output"]  # 已知价 + 兜底价


def test_cost_summary_uses_pricing():
    from app.llm.client import get_cost_summary

    summary = get_cost_summary([
        {"model": "deepseek-chat", "input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_hit_tokens": 1_000_000},
    ])
    # 输入全部命中缓存：0.02 + 输出 2.0
    assert summary["estimated_cost_rmb"] == 2.02
