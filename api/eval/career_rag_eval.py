"""Run the application RAG retriever against labeled Chinese documents in an isolated ES index."""

import argparse
import asyncio
import json
from copy import deepcopy
from math import ceil
from pathlib import Path
from time import perf_counter
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from elasticsearch import AsyncElasticsearch, helpers

from app.core.rag import search
from app.core.llm.resolver import get_optional_client_for_type
from app.core.rag.chunker import chunk_parent_child
from app.core.rag.es_index import CHUNK_TYPE_CHILD, CHUNK_TYPE_PARENT, _MAPPING
from app.core.rag.es_store import build_chunk_doc
from app.db.postgres import SessionLocal, close
from eval import metrics

FIXTURE = Path(__file__).with_name("fixtures") / "career_rag_gold.json"
MODEL = "lyf219/bge-small-zh-v1.5-onnx:bge-small-zh-v1.5.onnx"
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
TOP_K = 5


class LocalEmbedding:
    def __init__(self, model_dir):
        import onnxruntime
        from tokenizers import Tokenizer

        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=512)
        self.tokenizer.enable_padding()
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = 4
        self.session = onnxruntime.InferenceSession(
            str(model_dir / "bge-small-zh-v1.5.onnx"), sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self.inputs = {item.name for item in self.session.get_inputs()}

    def encode(self, texts):
        import numpy as np

        result = []
        for start in range(0, len(texts), 12):
            batch = self.tokenizer.encode_batch(texts[start:start + 12])
            values = {
                "input_ids": [value.ids for value in batch],
                "attention_mask": [value.attention_mask for value in batch],
                "token_type_ids": [value.type_ids for value in batch],
            }
            inputs = {key: np.asarray(values[key], dtype=np.int64) for key in self.inputs}
            vectors = self.session.run(None, inputs)[0][:, 0, :]
            result.extend((vectors / np.linalg.norm(vectors, axis=1, keepdims=True)).tolist())
        return result


class RecordedSearch:
    def __init__(self, client):
        self.client = client
        self.candidates = {}
        self.vector_requests = 0

    async def search(self, *, index, body):
        response = await self.client.search(index=index, body=body)
        if "knn" in body:
            mode = "vector"
            self.vector_requests += 1
        elif "must" in body["query"]["bool"]:
            mode = "bm25"
        else:
            return response
        self.candidates[mode] = [hit["_source"]["source_id"] for hit in response["hits"]["hits"]]
        return response


def indexed_parts(documents, uid, kb_id, index):
    parents = []
    children = []
    for document in documents:
        attrs = {"user_id": str(uid), "kb_id": kb_id, "source_type": "document",
                 "source_id": document["id"], "doc_name": document["title"]}
        for ordinal, parent in enumerate(chunk_parent_child(document["text"])):
            prefix = f"{document['id']}:{ordinal}"
            parent_id = f"{prefix}:parent"
            row = build_chunk_doc(**attrs, chunk_type=CHUNK_TYPE_PARENT, content=parent.content, vector=None)
            row.update(_index=index, _id=parent_id)
            row["_source"]["chunk_id"] = parent_id
            parents.append(row)
            for child_index, child in enumerate(parent.children):
                child_id = f"{prefix}:child:{child_index}"
                row = build_chunk_doc(**attrs, chunk_type=CHUNK_TYPE_CHILD, content=child,
                                      vector=None, parent_id=parent_id)
                row.update(_index=index, _id=child_id)
                row["_source"]["chunk_id"] = child_id
                children.append(row)
    return parents, children


def score(rows, method):
    rankings = [(row["ranked"][method], row["gold"]) for row in rows]
    covered = [set(ranked) & set(gold) for ranked, gold in rankings]
    result = {
        "recall_at_5": metrics.avg([metrics.recall_at_k(r, g, TOP_K) for r, g in rankings]),
        "hit_at_5": metrics.avg([bool(hits) for hits in covered]),
        "mrr_at_5": metrics.avg([metrics.mrr(r, g) for r, g in rankings]),
        "queries_with_hit": sum(bool(hits) for hits in covered),
        "queries_with_all_sources": sum(len(hits) == len(gold) for hits, (_, gold) in zip(covered, rankings, strict=True)),
        "queries": len(rows),
    }
    if method in {"fixed", "hybrid", "reranked"}:
        timings = sorted(row["retrieval_ms"][method] for row in rows)
        result["p95_retrieval_ms"] = timings[max(0, ceil(len(timings) * 0.95) - 1)] if timings else None
        result["mean_distinct_parent_results"] = metrics.avg([row["distinct_parents"][method] for row in rows])
        result["parent_slots_filled"] = sum(row["distinct_parents"][method] for row in rows)
        result["expanded_queries"] = sum(row["vector_requests"][method] > 1 for row in rows)
    return result


async def evaluate(url, model_dir, dataset, reranker=None):
    uid, kb_id = uuid4(), str(uuid4())
    index = f"career-rag-eval-{uid.hex}"
    documents, queries = dataset["documents"], dataset["queries"]
    known = {doc["id"] for doc in documents}
    if len(known) != len(documents) or len({row["id"] for row in queries}) != len(queries):
        raise ValueError("Duplicate fixture identifiers")
    if any(not row["relevant"] or not set(row["relevant"]) <= known for row in queries):
        raise ValueError("Query must reference at least one known document")
    parents, children = indexed_parts(documents, uid, kb_id, index)
    embedding = LocalEmbedding(model_dir)
    vector_input = [row["_source"]["content"] for row in children]
    vectors = embedding.encode(vector_input + [QUERY_PREFIX + row["query"] for row in queries])
    query_vectors = vectors[len(children):]
    for child, vector in zip(children, vectors[:len(children)], strict=True):
        child["_source"]["vector"] = vector
    mapping = deepcopy(_MAPPING)
    mapping["mappings"]["properties"]["vector"]["dims"] = len(vectors[0])
    rows = []
    rerank_ok = 0

    class CountedReranker:
        async def rerank(self, *args, **kwargs):
            nonlocal rerank_ok
            result = await reranker.rerank(*args, **kwargs)
            rerank_ok += bool(result)
            return result
    async with AsyncElasticsearch(url, request_timeout=15) as es:
        version = (await es.info())["version"]["number"]
        await es.indices.create(index=index, body=mapping)
        try:
            await helpers.async_bulk(es, [*parents, *children], refresh="wait_for")
            recorder = RecordedSearch(es)
            client = AsyncMock()
            with (patch.object(search, "get_es", return_value=recorder),
                  patch.object(search, "CHUNKS_INDEX", index),
                  patch.object(search, "get_client_for_type", return_value=client),
                  patch.object(search, "get_optional_client_for_type",
                               return_value=CountedReranker() if reranker else None)):
                for index_in_eval, (fixture, vector) in enumerate(zip(queries, query_vectors, strict=True)):
                    client.embed_one.return_value = vector
                    ran = {}
                    elapsed = {}
                    vector_requests = {}
                    fixed_candidates = {}
                    variants = [("fixed", False, False), ("hybrid", True, False)]
                    if index_in_eval % 2:
                        variants.reverse()
                    if reranker:
                        variants.append(("reranked", True, True))
                    for name, adaptive, use_reranker in variants:
                        recorder.candidates.clear()
                        recorder.vector_requests = 0
                        started = perf_counter()
                        ran[name] = await search.hybrid_search(None, uid, fixture["query"], top_k=TOP_K,
                                                               source_type="document", kb_ids=[kb_id],
                                                               adaptive=adaptive, rerank=use_reranker)
                        elapsed[name] = round((perf_counter() - started) * 1000, 2)
                        vector_requests[name] = recorder.vector_requests
                        if name == "fixed":
                            fixed_candidates = dict(recorder.candidates)
                    rows.append({"id": fixture["id"], "kind": fixture["kind"], "query": fixture["query"],
                                 "gold": fixture["relevant"], "ranked": {
                                     "bm25": fixed_candidates["bm25"][:TOP_K],
                                     "vector": fixed_candidates["vector"][:TOP_K],
                                     **{name: [hit["source_id"] for hit in values] for name, values in ran.items()},
                                 }, "retrieval_ms": elapsed, "vector_requests": vector_requests,
                                 "distinct_parents": {name: len({hit["parent_id"] for hit in values if hit["parent_id"]})
                                                      for name, values in ran.items()}})
        finally:
            await es.indices.delete(index=index)
    methods = ("bm25", "vector", "fixed", "hybrid") + (("reranked",) if reranker else ())
    kinds = sorted({row["kind"] for row in rows})
    return {"elasticsearch": version, "embedding": MODEL, "dimensions": len(vectors[0]),
            "documents": len(documents), "child_chunks": len(children), "queries": len(queries),
            "successful_rerank_queries": rerank_ok,
            "summary": {method: score(rows, method) for method in methods},
            "by_kind": {kind: {method: score([row for row in rows if row["kind"] == kind], method)
                               for method in methods} for kind in kinds}, "runs": rows}


async def _main(url, model_dir, data, user):
    if user is None:
        return await evaluate(url, model_dir, data)
    try:
        async with SessionLocal() as session:
            reranker = await get_optional_client_for_type(session, user, "rerank")
        if reranker is None:
            raise ValueError("该账户没有配置 Rerank 模型")
        return await evaluate(url, model_dir, data, reranker)
    finally:
        await close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--es-url", default="http://127.0.0.1:9200")
    parser.add_argument("--rerank-user", type=UUID, help="使用指定账户配置的 Rerank 模型评测固定公开语料")
    args = parser.parse_args()
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    print(json.dumps(asyncio.run(_main(args.es_url, args.model_dir, data, args.rerank_user)), ensure_ascii=False, indent=2))
