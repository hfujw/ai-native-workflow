"""测试 _filter_noise — 搜索结果的广告过滤。"""
from app.tools import _filter_noise


def test_filters_ad_keywords():
    results = [
        {"title": "长城门票团购", "snippet": "优惠促销"},
        {"title": "长城历史", "snippet": "建造背景"},
    ]
    filtered = _filter_noise(results)
    assert len(filtered) == 1
    assert filtered[0]["title"] == "长城历史"


def test_preserves_normal_results():
    results = [
        {"title": "图灵破译Enigma", "snippet": "二战密码学"},
        {"title": "Python教程", "snippet": "编程入门"},
    ]
    filtered = _filter_noise(results)
    assert len(filtered) == 2


def test_empty_list():
    assert _filter_noise([]) == []


def test_all_noise():
    results = [
        {"title": "酒店优惠", "snippet": "促销"},
        {"title": "股票推荐", "snippet": "基金理财"},
    ]
    assert _filter_noise(results) == []
