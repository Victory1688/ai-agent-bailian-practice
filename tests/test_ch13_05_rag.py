"""
test_ch13_05_rag.py —— chapter13 / 05 RAG 检索问答子系统

【TDD 定位】被测文件：chapter13/05_RAG检索问答子系统.py
【测试策略】cosine / split_text / JSONCache = 纯函数与本地 IO，全量确定性断言；
            嵌入与问答真实调用 = @pytest.mark.live

【本篇要守住的契约】（来自源码逐行核对，非臆造）
  - EmbeddingClient.cosine：正交为 0、同向为 1、零向量返回 0.0（不除零）
  - split_text：按段落切；超长段落滑窗（step = chunk_size - overlap）
  - split_text：空段落被过滤；结果无空串
  - JSONCache：get/set 往返一致；未命中返回 None
  - EmbeddingClient.embed：缓存命中不增加 api_calls（核心优化验证）
  - KnowledgeBase.search 返回按相似度降序的 k 个片段
"""

import math
import os
import json
import tempfile
import pytest

pytestmark = pytest.mark.usefixtures("ch13_05")


# ============================================================
# 1. cosine —— 纯数学（最值得 TDD 的部分）
# ============================================================

def test_cosine_identical_vectors(ch13_05):
    """同向向量相似度为 1.0"""
    assert ch13_05.EmbeddingClient.cosine([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)


def test_cosine_orthogonal(ch13_05):
    """正交向量相似度为 0.0"""
    assert ch13_05.EmbeddingClient.cosine([1, 0], [0, 1]) == pytest.approx(0.0)


def test_cosine_opposite(ch13_05):
    """反向向量相似度为 -1.0"""
    assert ch13_05.EmbeddingClient.cosine([1, 0], [-1, 0]) == pytest.approx(-1.0)


def test_cosine_zero_vector_no_div_error(ch13_05):
    """零向量必须返回 0.0（不得 ZeroDivisionError）—— 源码 norm else 0.0"""
    assert ch13_05.EmbeddingClient.cosine([0, 0, 0], [1, 2, 3]) == 0.0
    assert ch13_05.EmbeddingClient.cosine([1, 2, 3], [0, 0, 0]) == 0.0


def test_cosine_scale_invariant(ch13_05):
    """余弦相似度对向量长度（模长）不敏感"""
    a = ch13_05.EmbeddingClient.cosine([1, 2, 3], [2, 4, 6])
    assert a == pytest.approx(1.0)


def test_cosine_is_symmetric(ch13_05):
    """对称性：cos(a,b) == cos(b,a)"""
    a, b = [3, 1, 4], [1, 5, 9]
    assert ch13_05.EmbeddingClient.cosine(a, b) == pytest.approx(
        ch13_05.EmbeddingClient.cosine(b, a))


# ============================================================
# 2. split_text —— 分块
# ============================================================

def test_split_short_paragraphs(ch13_05):
    """短段落各成一块"""
    text = "第一段。\n第二段。\n第三段。"
    chunks = ch13_05.split_text(text, chunk_size=200)
    assert chunks == ["第一段。", "第二段。", "第三段。"]


def test_split_filters_blank_paragraphs(ch13_05):
    """空行 / 纯空白段落必须被过滤，结果无空串"""
    text = "第一段。\n\n   \n第二段。\n"
    chunks = ch13_05.split_text(text, chunk_size=200)
    assert chunks == ["第一段。", "第二段。"]
    assert all(c.strip() for c in chunks)


def test_split_long_paragraph_sliding_window(ch13_05):
    """超长段落必须滑窗切分，且每块不超过 chunk_size"""
    long_para = "A" * 500
    chunks = ch13_05.split_text(long_para, chunk_size=200, overlap=20)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)


def test_split_overlap_produces_shared_content(ch13_05):
    """滑窗应有重叠（overlap 生效）—— 相邻块存在共享字符"""
    long_para = "".join(str(i % 10) for i in range(300))
    chunks = ch13_05.split_text(long_para, chunk_size=100, overlap=20)
    if len(chunks) >= 2:
        assert chunks[0][-20:] == chunks[1][:20]


def test_split_empty_input(ch13_05):
    """空输入返回空列表"""
    assert ch13_05.split_text("") == []
    assert ch13_05.split_text("\n\n\n") == []


def test_split_preserves_content_order(ch13_05):
    """分块顺序必须与原文本一致"""
    text = "甲\n乙\n丙\n丁"
    chunks = ch13_05.split_text(text)
    assert chunks == ["甲", "乙", "丙", "丁"]


# ============================================================
# 3. JSONCache —— 本地持久化
# ============================================================

def test_cache_roundtrip(ch13_05, tmp_path):
    """set 后 get 应返回相同值"""
    path = str(tmp_path / "c.json")
    cache = ch13_05.JSONCache(path)
    cache.set("k1", {"vec": [1, 2, 3]})
    assert cache.get("k1") == {"vec": [1, 2, 3]}


def test_cache_miss_returns_none(ch13_05, tmp_path):
    """未命中返回 None"""
    cache = ch13_05.JSONCache(str(tmp_path / "c.json"))
    assert cache.get("不存在") is None


def test_cache_persists_to_disk(ch13_05, tmp_path):
    """缓存必须落盘：新实例能读到旧实例写入的值"""
    path = str(tmp_path / "c.json")
    ch13_05.JSONCache(path).set("k", "v")
    assert os.path.isfile(path)
    assert ch13_05.JSONCache(path).get("k") == "v"


def test_cache_file_is_valid_json(ch13_05, tmp_path):
    """落盘内容必须是合法 JSON（可被外部工具读取）"""
    path = str(tmp_path / "c.json")
    cache = ch13_05.JSONCache(path)
    cache.set("a", [1, 2])
    cache.set("b", [3, 4])
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["a"] == [1, 2] and data["b"] == [3, 4]


def test_cache_key_is_md5_hex(ch13_05):
    """缓存键必须是 32 位 md5 hex（结构化键，非原文）"""
    k = ch13_05.EmbeddingClient._key("测试文本")
    assert len(k) == 32 and all(c in "0123456789abcdef" for c in k)


def test_cache_key_deterministic(ch13_05):
    """同文本键必须稳定（缓存命中的前提）"""
    assert ch13_05.EmbeddingClient._key("同样的文本") == ch13_05.EmbeddingClient._key("同样的文本")


def test_cache_key_differs_for_diff_text(ch13_05):
    """不同文本键必须不同"""
    assert ch13_05.EmbeddingClient._key("A") != ch13_05.EmbeddingClient._key("B")


# ============================================================
# 4. 常量契约
# ============================================================

def test_embedding_model_name(ch13_05):
    """嵌入模型必须是 text-embedding-v3"""
    assert ch13_05.EMBEDDING_MODEL == "text-embedding-v3"


def test_embed_batch_limit(ch13_05):
    """批处理上限应为 10（API 单批上限）"""
    assert ch13_05.EMBED_BATCH == 10


def test_top_k_default_two(ch13_05):
    """默认检索 2 个片段（教材 k=2 语义）"""
    assert ch13_05.TOP_K == 2


# ============================================================
# 5. 真实链路（含缓存命中验证）
# ============================================================

@pytest.mark.live
def test_embed_cache_hit_avoids_api_call(ch13_05, tmp_path):
    """核心优化验证：同一文本二次嵌入必须命中缓存（api_calls 不增加）"""
    cache = ch13_05.JSONCache(str(tmp_path / "c.json"))
    client = ch13_05.EmbeddingClient(cache)
    v1 = client.embed(["人工智能"])
    calls_after_first = client.api_calls
    assert calls_after_first >= 1
    v2 = client.embed(["人工智能"])
    assert client.api_calls == calls_after_first, "二次嵌入未命中缓存 —— 缓存失效"
    assert v1[0] == v2[0]


@pytest.mark.live
def test_embed_dimension_1024(ch13_05, tmp_path):
    """嵌入向量维度应为 1024"""
    cache = ch13_05.JSONCache(str(tmp_path / "c.json"))
    vec = ch13_05.EmbeddingClient(cache).embed(["测试"])[0]
    assert len(vec) == 1024


@pytest.mark.live
def test_knowledge_base_search(ch13_05, tmp_path):
    """知识库检索返回非空片段，且按相似度降序"""
    cache = ch13_05.JSONCache(str(tmp_path / "c.json"))
    embedder = ch13_05.EmbeddingClient(cache)
    kb = ch13_05.KnowledgeBase(ch13_05.KNOWLEDGE_TEXT, embedder)
    assert len(kb.chunks) >= 1
    hits = kb.search("什么是人工智能", k=2)
    assert 1 <= len(hits) <= 2
    assert all(isinstance(h, str) and h.strip() for h in hits)


@pytest.mark.live
def test_rag_agent_ask_contract(ch13_05, tmp_path):
    """RAGAgent.ask 返回结构化 {success, answer, sources}（错误不混流）"""
    cache = ch13_05.JSONCache(str(tmp_path / "c.json"))
    embedder = ch13_05.EmbeddingClient(cache)
    kb = ch13_05.KnowledgeBase(ch13_05.KNOWLEDGE_TEXT, embedder)
    agent = ch13_05.RAGAgent(kb)
    result = agent.ask("人工智能是什么")
    assert isinstance(result, dict)
    assert set(result.keys()) == {"success", "answer", "sources"}
    assert result["success"] is True, result.get("error")
    assert result["answer"].strip()
    assert isinstance(result["sources"], list)
