"""模型费率表（元/百万 token）——换模型换价格，只改这张表。

来源：https://api-docs.deepseek.com/quick_start/pricing
费率会变，上线前请按官网核对。未知模型（用户自定义添加）按兜底价计——
护栏原则：宁可高估预算，不少算。
"""

# 每百万 token 价格（元）
# 官方现行命名（2026）：deepseek-v4-flash（原 deepseek-chat 对应款）、
# deepseek-v4-pro（原 deepseek-reasoner 对应款）。旧名保留作兼容（同价）。
PRICING: dict[str, dict[str, float]] = {
    "deepseek-v4-flash": {"input_cached": 0.02, "input_miss": 1.0, "output": 2.0},
    "deepseek-chat": {"input_cached": 0.02, "input_miss": 1.0, "output": 2.0},  # 旧名兼容
    # TODO: 官网核对 deepseek-v4-pro 真实费率，当前沿用 reasoner 保守占位
    "deepseek-v4-pro": {"input_cached": 0.02, "input_miss": 2.0, "output": 8.0},
    "deepseek-reasoner": {"input_cached": 0.02, "input_miss": 2.0, "output": 8.0},  # 旧名兼容
}

# 未知模型兜底（按较高价，预算更安全）
FALLBACK: dict[str, float] = {"input_cached": 0.1, "input_miss": 4.0, "output": 8.0}


def get_price(model: str | None) -> dict[str, float]:
    """按模型取费率；未知/缺省模型用兜底价。"""
    if model:
        p = PRICING.get(model)
        if p is not None:
            return p
    return FALLBACK


def compute_cost(records: list[dict]) -> float:
    """按每条记录的 model 分别计价，累计总成本（元）。

    账本条目字段：input_tokens / output_tokens / cache_hit_tokens / model
    """
    cost = 0.0
    for r in records:
        price = get_price(r.get("model"))
        hit = r.get("cache_hit_tokens", 0)
        miss = max(0, r.get("input_tokens", 0) - hit)
        out = r.get("output_tokens", 0)
        cost += (
            hit / 1_000_000 * price["input_cached"]
            + miss / 1_000_000 * price["input_miss"]
            + out / 1_000_000 * price["output"]
        )
    return cost
