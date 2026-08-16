"""pytest 共享 fixture。"""
import os
import sys

import pytest

# 确保 backend 在 sys.path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def sample_material():
    """模拟 4 条搜索结果——3 条相关，1 条不相关。"""
    return [
        {"title": "秦始皇统一六国", "snippet": "公元前221年秦始皇完成统一", "content": ""},
        {"title": "长城修建", "snippet": "秦始皇征发民夫修建长城", "content": ""},
        {"title": "兵马俑发现", "snippet": "1974年陕西农民发现兵马俑", "content": ""},
        {"title": "Python入门教程", "snippet": "Python是一种编程语言", "content": ""},
    ]
