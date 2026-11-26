"""混合检索：向量召回 + BM25 召回 → 加权融合 →（可选）rerank 重排。

强制 user_id 过滤做多租户隔离。命中子块后返回其父块内容提供更大上下文。
"""
import asyncio
import uuid
from time import monotonic

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm.resolver import get_client_for_type, get_optional_client_for_type
from app.core.logging import get_logger
from app.core.rag.es_index import CHUNK_TYPE_CHILD, CHUNK_TYPE_IMAGE, CHUNK_TYPE_PARENT, CHUNKS_INDEX
from app.db.elastic import get_es

logger = get_logger(__name__)

# 融合权重
_VECTOR_WEIGHT = 0.6
_BM25_WEIGHT = 0.4
_MAX_ADAPTIVE_RECALL = 120


def _normalize(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    vals = list(scores.values())
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        return {k: 1.0 for k in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores.items()}


async def hybrid_search(
    session: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    top_k: int = 5,
    recall_size: int = 20,
    tags: list[str] | None = None,
    source_type: str | None = None,
    min_vector_score: float | None = None,
    kb_ids: list[str] | None = None,
    *, adaptive: bool = True, rerank: bool = True,
) -> list[dict]:
    """混合检索，返回 top_k 个结果（含 content / doc_name / source_id / score）。

    source_type 可选 document / image，在 ES 召回阶段就过滤，避免跨类型互相淹没。
    文档检索命中 child 子块（再取父块上下文）；图片检索命中 image_desc 块。

    kb_ids 不为空时限定只检索这些知识库的内容（对话时取"已启用检索"的库集合）。
    传入空列表 [] 表示没有任何启用的库 → 直接返回空（不检索）。

    min_vector_score 不为 None 时启用「绝对相关度门控」（精确导向，用于全局搜索）：
    只保留 BM25 命中 或 向量原始余弦得分 ≥ 阈值的结果，丢弃不相关的最近邻噪声。
    """
    if top_k <= 0 or recall_size <= 0 or kb_ids == []:
        return []
    es = get_es()
    uid = str(user_id)

    # 文档用 child 子块；图片用 image_desc 块
    if source_type == "image":
        chunk_types = [CHUNK_TYPE_IMAGE]
    elif source_type == "document":
        chunk_types = [CHUNK_TYPE_CHILD]
    else:
        # 不限来源：同时检索文档子块和图片描述块
        chunk_types = [CHUNK_TYPE_CHILD, CHUNK_TYPE_IMAGE]

    base_filter: list[dict] = [
        {"term": {"user_id": uid}},
        {"terms": {"chunk_type": chunk_types}},
    ]
    if kb_ids is not None:
        base_filter.append({"terms": {"kb_id": kb_ids}})
    if tags:
        base_filter.append({"terms": {"tags": tags}})
    if source_type:
        base_filter.append({"term": {"source_type": source_type}})

    # 1. 向量召回
    embed_client = await get_client_for_type(session, user_id, "embedding")
    query_vector = await embed_client.embed_one(query)
    started = monotonic()
    size = max(recall_size, top_k)
    ceiling = max(size, min(_MAX_ADAPTIVE_RECALL, max(2 * size, 4 * top_k)))
    hits, candidate_ids, scores, full_window = await _rank_candidates(
        es, base_filter, query, query_vector, size, min_vector_score,
    )
    if adaptive and full_window and size < ceiling and _distinct_candidates(hits, candidate_ids) < top_k:
        try:
            hits, candidate_ids, scores, _ = await _rank_candidates(
                es, base_filter, query, query_vector, ceiling, min_vector_score,
            )
            size = ceiling
        except Exception as error:
            logger.warning("RAG expanded recall unavailable type=%s", type(error).__name__)

    reranked_ok = False
    if rerank and min_vector_score is None and candidate_ids:
        try:
            rerank_client = await get_optional_client_for_type(session, user_id, "rerank")
            if rerank_client:
                docs = [hits[cid]["content"] for cid in candidate_ids]
                reranked = await rerank_client.rerank(query, docs, top_n=len(candidate_ids))
                reranked_ids = [candidate_ids[idx] for idx, _ in reranked if 0 <= idx < len(candidate_ids)]
                candidate_ids = list(dict.fromkeys([*reranked_ids, *candidate_ids]))
                reranked_ok = bool(reranked_ids)
        except Exception as error:
            logger.warning("RAG rerank unavailable type=%s", type(error).__name__)
    result = await _collect_results(es, uid, hits, candidate_ids, scores, top_k)
    logger.debug("RAG retrieval window=%d reranked=%s result_count=%d target=%d elapsed_ms=%.1f",
                 size, reranked_ok, len(result), top_k, (monotonic() - started) * 1000)
    return result


def _distinct_candidates(hits, candidates) -> int:
    return len({(hits[cid].get("source_id"), hits[cid].get("kb_id"), hits[cid].get("parent_id") or cid)
                for cid in candidates})


async def _rank_candidates(es, base_filter, query, query_vector, recall_size, min_vector_score):
    knn = es.search(
        index=CHUNKS_INDEX,
        body={
            "size": recall_size,
            "query": {"bool": {"filter": base_filter}},
            "knn": {
                "field": "vector",
                "query_vector": query_vector,
                "k": recall_size,
                "num_candidates": recall_size * 5,
                "filter": {"bool": {"filter": base_filter}},
            },
        },
    )

    # 2. BM25 召回
    if min_vector_score is not None:
        rows = (await knn)["hits"]["hits"]
        hits = {row["_id"]: row["_source"] for row in rows}
        scores = {row["_id"]: 2 * row["_score"] - 1 for row in rows if 2 * row["_score"] - 1 >= min_vector_score}
        return hits, sorted(scores, key=scores.get, reverse=True), scores, len(rows) >= recall_size

    knn_resp, bm25_resp = await asyncio.gather(knn, es.search(
        index=CHUNKS_INDEX,
        body={
            "size": recall_size,
            "query": {
                "bool": {
                    "must": [{"match": {"content": query}}],
                    "filter": base_filter,
                }
            },
        },
    ))

    # 3. 收集 + 归一化 + 加权融合
    hits: dict[str, dict] = {}
    vec_scores: dict[str, float] = {}
    bm_scores: dict[str, float] = {}
    for h in knn_resp["hits"]["hits"]:
        hits[h["_id"]] = h["_source"]
        vec_scores[h["_id"]] = h["_score"]
    for h in bm25_resp["hits"]["hits"]:
        hits[h["_id"]] = h["_source"]
        bm_scores[h["_id"]] = h["_score"]

    vec_n = _normalize(vec_scores)
    bm_n = _normalize(bm_scores)
    fused: dict[str, float] = {}
    for cid in hits:
        fused[cid] = (
            _VECTOR_WEIGHT * vec_n.get(cid, 0.0) + _BM25_WEIGHT * bm_n.get(cid, 0.0)
        )

    return hits, sorted(fused, key=fused.get, reverse=True)[:recall_size], fused, len(hits) >= recall_size


async def _collect_results(
    es, user_id: str, hits: dict[str, dict], candidate_ids: list[str],
    scores: dict[str, float], top_k: int,
) -> list[dict]:
    parent_ids = {hits[cid]["parent_id"] for cid in candidate_ids if hits[cid].get("parent_id")}
    parents = {}
    if parent_ids:
        resp = await es.search(
            index=CHUNKS_INDEX,
            body={
                "size": len(parent_ids),
                "query": {"bool": {"filter": [
                    {"term": {"user_id": user_id}},
                    {"term": {"chunk_type": CHUNK_TYPE_PARENT}},
                    {"terms": {"chunk_id": sorted(parent_ids)}},
                ]}},
            },
        )
        parents = {hit["_source"]["chunk_id"]: hit["_source"] for hit in resp["hits"]["hits"]}

    results: list[dict] = []
    seen = set()
    for cid in candidate_ids:
        src = hits[cid]
        parent = parents.get(src.get("parent_id"))
        if parent and any(parent.get(key) != src.get(key) for key in ("source_id", "kb_id")):
            parent = None
        result_key = ("parent", parent["chunk_id"]) if parent else ("chunk", cid)
        if result_key in seen:
            continue
        seen.add(result_key)
        results.append(
            {
                "chunk_id": cid,
                "parent_id": parent["chunk_id"] if parent else None,
                "content": (parent or src).get("content", ""),
                "doc_name": src.get("doc_name"),
                "source_id": src.get("source_id"),
                "source_type": src.get("source_type"),
                "kb_id": src.get("kb_id"),
                "score": round(scores[cid], 4),
            }
        )
        if len(results) == top_k:
            break
    return results
