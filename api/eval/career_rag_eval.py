"""Run the application RAG retriever against labeled Chinese documents in an isolated ES index."""

import argparse
import asyncio
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from elasticsearch import AsyncElasticsearch, helpers

from app.core.rag import search
from app.core.rag.chunker import chunk_parent_child
from app.core.rag.es_index import CHUNK_TYPE_CHILD, CHUNK_TYPE_PARENT, _MAPPING
from app.core.rag.es_store import build_chunk_doc
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

    async def search(self, *, index, body):
        response = await self.client.search(index=index, body=body)
        if "knn" in body:
            mode = "vector"
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
    return {
        "recall_at_5": metrics.avg([metrics.recall_at_k(r, g, TOP_K) for r, g in rankings]),
        "hit_at_5": metrics.avg([bool(hits) for hits in covered]),
        "mrr_at_5": metrics.avg([metrics.mrr(r, g) for r, g in rankings]),
        "queries_with_hit": sum(bool(hits) for hits in covered),
        "queries_with_all_sources": sum(len(hits) == len(gold) for hits, (_, gold) in zip(covered, rankings, strict=True)),
        "queries": len(rows),
    }


async def evaluate(url, model_dir, dataset):
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
                  patch.object(search, "get_optional_client_for_type", return_value=None)):
                for fixture, vector in zip(queries, query_vectors, strict=True):
                    client.embed_one.return_value = vector
                    recorder.candidates.clear()
                    hybrid = await search.hybrid_search(None, uid, fixture["query"], top_k=TOP_K,
                                                        source_type="document", kb_ids=[kb_id])
                    rows.append({"id": fixture["id"], "kind": fixture["kind"], "query": fixture["query"],
                                 "gold": fixture["relevant"], "ranked": {
                                     "bm25": recorder.candidates["bm25"][:TOP_K],
                                     "vector": recorder.candidates["vector"][:TOP_K],
                                     "hybrid": [hit["source_id"] for hit in hybrid],
                                 }})
        finally:
            await es.indices.delete(index=index)
    methods = ("bm25", "vector", "hybrid")
    kinds = sorted({row["kind"] for row in rows})
    return {"elasticsearch": version, "embedding": MODEL, "dimensions": len(vectors[0]),
            "documents": len(documents), "child_chunks": len(children), "queries": len(queries),
            "summary": {method: score(rows, method) for method in methods},
            "by_kind": {kind: {method: score([row for row in rows if row["kind"] == kind], method)
                               for method in methods} for kind in kinds}, "runs": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--es-url", default="http://127.0.0.1:9200")
    args = parser.parse_args()
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    print(json.dumps(asyncio.run(evaluate(args.es_url, args.model_dir, data)), ensure_ascii=False, indent=2))
