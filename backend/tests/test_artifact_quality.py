"""产物质量自动评估测试——五维底线可重复判定，不靠肉眼。"""

from app.observability.artifact_quality import assess_artifact

# 一个"合格"的教育产物：标题、多段、结构块、来源、互动
GOOD_HTML = """<!DOCTYPE html><html lang="zh-CN"><head><style>
h1{font-size:36px} p{font-size:16px} .card{border:1px solid #ccc} a:hover{color:red}
</style></head><body>
<h1>恐龙为什么灭绝</h1>
<p>大约6600万年前，一颗小行星撞击了今天的墨西哥尤卡坦半岛。</p>
<p>这次撞击引发了全球性的气候剧变，导致非鸟类恐龙灭绝。</p>
<blockquote>科学界主流观点认为撞击说最有说服力。</blockquote>
<a href="https://example.com">参考来源</a>
<button onclick="toggle()">查看细节</button>
</body></html>"""

# 一个"不合格"的产物：一坨长文字，无结构无来源无互动
BAD_HTML = """<!DOCTYPE html><html><body>
<div>这是一个非常长的段落，没有标题没有分段没有结构，全是一整块文字堆在这里，洋洋洒洒几百个字没有任何视觉层次，也没有任何数据来源引用，更没有可点击的交互元素，这样的页面对于儿童来说读起来非常困难，因为它完全违背了教育内容的组织原则。</div>
</body></html>"""


def test_good_artifact_full_score():
    """合格产物：6 维全过。"""
    result = assess_artifact(GOOD_HTML)
    assert result["score"] == 6, result["results"]


def test_bad_artifact_low_score():
    """不合格产物：一坨文字，最多 1 维（无标题体系/无结构块/无来源/无互动）。"""
    result = assess_artifact(BAD_HTML)
    # 一坨文字：无 h1/h2 → 信息架构不过；无段落 → 段落长度不过；无来源/互动 → 0
    assert result["score"] <= 1, result["results"]
    assert result["results"]["信息架构"][0] is False


def test_education_dimension():
    """教育适配：有引导提问 → 过；纯静态长文无提问 → 不过。"""
    # GOOD_HTML 里有 "为什么" 提问 + button → 教育适配过
    assert assess_artifact(GOOD_HTML)["results"]["教育适配"][0] is True
    # 无提问、无交互的静态内容 → 教育适配不过
    static_html = "<html><body><h1>标题</h1><p>第一段内容。</p><p>第二段内容。</p></body></html>"
    assert assess_artifact(static_html)["results"]["教育适配"][0] is False


def test_info_architecture_dimension():
    """信息架构：无 h1 或无段落 → 不过。"""
    no_h1 = "<html><body><p>一段</p><p>两段</p></body></html>"
    assert assess_artifact(no_h1)["results"]["信息架构"][0] is False
    single_para = "<html><body><h1>标题</h1><p>只有一段</p></body></html>"
    assert assess_artifact(single_para)["results"]["信息架构"][0] is False


def test_visual_hierarchy_dimension():
    """视觉层次：有标题但无结构块/分隔 → 不过。"""
    no_blocks = "<html><body><h1>标题</h1><p>一段</p><p>两段</p></body></html>"
    assert assess_artifact(no_blocks)["results"]["视觉层次"][0] is False


def test_paragraph_length_dimension():
    """段落长度：超阈值 → 不过。"""
    long_para = "<html><body><h1>标题</h1><p>" + "很长的段落内容。" * 60 + "</p><p>正常段。</p></body></html>"
    result = assess_artifact(long_para)
    assert result["results"]["段落长度"][0] is False


def test_fact_anchor_dimension():
    """事实锚定：无链接无来源字样 → 不过。"""
    no_source = "<html><body><h1>标题</h1><p>一段</p><p>两段</p><div class='card'>块</div><button>点</button></body></html>"
    assert assess_artifact(no_source)["results"]["事实锚定"][0] is False


def test_interactive_dimension():
    """互动元素：有按钮但无 hover/click → 不算互动。"""
    no_interaction = "<html><body><h1>标题</h1><p>一段</p><p>两段</p><div class='card'>块</div><span>来源标注</span></body></html>"
    result = assess_artifact(no_interaction)
    assert result["results"]["互动元素"][0] is False
