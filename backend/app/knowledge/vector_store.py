"""向量语义检索 — ChromaDB + 中文 embedding 模型。

将 169 个本地示例话题做 embedding，搜的时候比较语义相似度。
"嬴政" 能匹配到 "秦始皇"——关键词做不到的，向量能做到。

中文模型 shibing624/text2vec-base-chinese：专门为中文语义训练。
通过 HF 镜像（hf-mirror.com）下载，国内无需代理。首次下载 ~400MB。
"""

import logging
import os

from .kb import ALL_EVENTS, _name

logger = logging.getLogger(__name__)

_collection = None
_CHINESE_MODEL = "shibing624/text2vec-base-chinese"
# P3：锚定项目目录，不随启动 CWD 漂移——否则从不同目录启动会重建向量库
_CHROMA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "chroma_data")


def _get_collection():
    """延迟初始化——首次调用时下载中文 embedding 模型（走国内镜像）。"""
    global _collection
    if _collection is not None:
        return _collection

    try:
        import chromadb
        from chromadb.utils import embedding_functions
    except ImportError:
        logger.warning("ChromaDB 未安装，向量检索不可用。pip install chromadb")
        return None

    # 走 HF 国内镜像，不需要代理
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

    try:
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=_CHINESE_MODEL,
        )
    except Exception as e:
        logger.warning("中文 embedding 模型下载失败，向量检索不可用: %s", e)
        return None

    os.makedirs(os.path.dirname(_CHROMA_DIR), exist_ok=True)
    client = chromadb.PersistentClient(path=_CHROMA_DIR)
    _collection = client.get_or_create_collection(
        name="topics_cn",
        embedding_function=ef,
    )

    if _collection.count() == 0:
        _init_data(_collection)

    return _collection


def _init_data(collection):
    """把全部示例话题写入向量库——只跑一次。"""
    ids, docs, metadatas = [], [], []
    for i, event in enumerate(ALL_EVENTS):
        title = _name(event)
        facts = event.get("facts", {})
        # 拼接可搜索文本
        text = f"{title}。{facts.get('story', '')}。{facts.get('fun_fact', '')}"
        ids.append(str(i))
        docs.append(text)
        metadatas.append({"title": title})

    collection.add(ids=ids, documents=docs, metadatas=metadatas)
    logger.info("向量库初始化完成：%d 条话题", len(ALL_EVENTS))


def vector_search(query: str, top_k: int = 3, min_distance: float = 1.5) -> list[dict]:
    """语义搜索。返回 [{title, content, distance}, ...]，按相似度降序。distance 越小越相似。"""
    col = _get_collection()
    if col is None:
        return []

    try:
        results = col.query(query_texts=[query], n_results=top_k)
    except Exception as e:
        logger.warning("向量搜索失败: %s", e)
        return []

    hits = []
    ids = results.get("ids", [[]])[0]
    distances = results.get("distances", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]

    for i, doc_id in enumerate(ids):
        if distances[i] > min_distance:
            continue
        hits.append({
            "title": metadatas[i].get("title", ""),
            "distance": round(distances[i], 3),
        })

    return hits
