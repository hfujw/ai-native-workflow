"""测试 strip_fence — 各种 LLM 输出格式。"""
from app.llm.parser import strip_fence


def test_no_fence():
    assert strip_fence('{"tool": "search"}') == '{"tool": "search"}'


def test_json_fence():
    result = strip_fence('```json\n{"tool": "search"}\n```')
    assert result == '{"tool": "search"}'


def test_html_fence():
    result = strip_fence('```html\n<div>hello</div>\n```')
    assert result == '<div>hello</div>'


def test_python_fence():
    result = strip_fence('```python\nprint(1)\n```')
    assert result == 'print(1)'


def test_generic_fence():
    result = strip_fence('```\nsome text\n```')
    assert result == 'some text'


def test_only_opening_fence():
    result = strip_fence('```json\n{"a": 1}')
    assert result == '{"a": 1}'


def test_only_closing_fence():
    result = strip_fence('{"a": 1}\n```')
    assert result == '{"a": 1}'


def test_empty_string():
    assert strip_fence("") == ""
