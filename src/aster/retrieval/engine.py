"""Scoped BM25 + BGE-M3/FAISS retrieval, RRF fusion, cross-encoder reranking."""

import hashlib
import importlib.util
import json
import math
import os
import re
import threading
from collections import Counter, OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import httpx

from aster.retrieval.corpus import CHUNKER, Corpus, Evidence
from aster.domain.models import IndexManifest
from aster.domain.service import Problem

TOKEN = re.compile(r"[a-z0-9_µμα-ω]+(?:[.\-][a-z0-9_µμα-ω]+)*|[\u3400-\u9fff]+", re.I)


def tokenize(text):
    result = []
    for token in TOKEN.findall(text.lower()):
        if re.fullmatch(r"[\u3400-\u9fff]+", token):
            result.extend(token)
            result.extend(token[i : i + 2] for i in range(len(token) - 1))
        else:
            result.append(token)
    return result


class BM25Index:
    """Precomputed postings for one fixed, already-authorized corpus snapshot."""

    def __init__(self, documents, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.size = len(documents)
        self.lengths = np.zeros(self.size, dtype=np.float64)
        postings = {}
        for position, document in enumerate(documents):
            counts = Counter(tokenize(document))
            self.lengths[position] = sum(counts.values())
            for term, frequency in counts.items():
                indexes, frequencies = postings.setdefault(term, ([], []))
                indexes.append(position)
                frequencies.append(frequency)
        self.average = float(self.lengths.mean()) if self.size else 1.0
        self.average = self.average or 1.0
        self.postings = {
            term: (np.asarray(indexes, dtype=np.int32), np.asarray(frequencies, dtype=np.float64))
            for term, (indexes, frequencies) in postings.items()
        }

    def score(self, query):
        scores = np.zeros(self.size, dtype=np.float32)
        for term in sorted(set(tokenize(query))):
            entry = self.postings.get(term)
            if entry is None:
                continue
            indexes, frequencies = entry
            idf = math.log(1 + (self.size - len(indexes) + 0.5) / (len(indexes) + 0.5))
            values = (
                idf
                * frequencies
                * (self.k1 + 1)
                / (
                    frequencies
                    + self.k1 * (1 - self.b + self.b * self.lengths[indexes] / self.average)
                )
            )
            scores[indexes] += values.astype(np.float32)
        return scores


def bm25(query, documents, k1=1.5, b=0.75):
    return BM25Index(documents, k1, b).score(query)


def rrf(rankings, k=60):
    score = {}
    for ranking in rankings:
        for rank, key in enumerate(dict.fromkeys(ranking), 1):
            score[key] = score.get(key, 0) + 1 / (k + rank)
    return score


def model_path(name, data_dir):
    explicit = Path(name).expanduser()
    if explicit.is_dir() and (explicit / "config.json").is_file():
        return explicit.resolve()
    local = Path(data_dir) / "models" / name.split("/")[-1]
    if (local / "config.json").is_file() and any(
        (local / f).is_file() for f in ["model.safetensors", "pytorch_model.bin"]
    ):
        return local
    hub = (
        Path(os.environ.get("HF_HOME", str(Path.home() / ".cache/huggingface")))
        / "hub"
        / ("models--" + name.replace("/", "--"))
    )
    ref = hub / "refs/main"
    if ref.is_file():
        snapshot = hub / "snapshots" / ref.read_text().strip()
        if (snapshot / "config.json").is_file():
            return snapshot
    return None


class LocalModels:
    def __init__(self, settings):
        self.settings = settings
        self.embedding = None
        self.reranker = None
        self.lock = threading.RLock()
        self.remote = (
            httpx.Client(base_url=settings.retrieval_url.rstrip("/"), timeout=180, trust_env=False)
            if settings.retrieval_url
            else None
        )

    def status(self):
        paths = [
            model_path(self.settings.embedding_model, self.settings.data_dir),
            model_path(self.settings.reranker_model, self.settings.data_dir),
        ]
        dependencies = all(
            importlib.util.find_spec(n) is not None for n in ["sentence_transformers", "faiss"]
        )
        status = {
            "available": dependencies and all(paths),
            "dependencies": dependencies,
            "embedding_ready": bool(paths[0]),
            "reranker_ready": bool(paths[1]),
            "embedding_model": self.settings.embedding_model,
            "reranker_model": self.settings.reranker_model,
            "device": self.settings.retrieval_device,
        }
        if self.remote:
            try:
                response = self.remote.get("/health")
                response.raise_for_status()
                health = response.json()
                if health["fingerprint"] != self.fingerprint():
                    raise ValueError("retrieval model revision mismatch")
                status.update(
                    available=bool(dependencies and all(paths)),
                    device=health["device"],
                    precision=health["precision"],
                    transport="local_worker",
                )
            except (httpx.HTTPError, ValueError, KeyError) as error:
                status.update(available=False, worker_error=str(error)[:200])
        return status

    def fingerprint(self):
        result = {}
        for label, name in [
            ("embedding", self.settings.embedding_model),
            ("reranker", self.settings.reranker_model),
        ]:
            path = model_path(name, self.settings.data_dir)
            version = None
            if path:
                stamp = path / "zhixu-model.json"
                if stamp.is_file():
                    version = json.loads(stamp.read_text()).get("revision")
                else:
                    version = (
                        path.name
                        if len(path.name) == 40
                        else hashlib.sha256((path / "config.json").read_bytes()).hexdigest()
                    )
            result[label] = {"name": name, "revision": version, "max_length": 1536}
        return result

    def encode(self, texts):
        with self.lock:
            if self.remote:
                response = self.remote.post("/encode", json={"texts": texts})
                response.raise_for_status()
                return np.asarray(response.json()["vectors"], dtype=np.float32)
            if self.embedding is None:
                status = self.status()
                if not status["dependencies"] or not status["embedding_ready"]:
                    raise Problem("完整检索模型尚未准备好，请运行 zhixu models --download", 503)
                import torch
                from sentence_transformers import SentenceTransformer

                torch.set_num_threads(int(os.getenv("ZHIXU_MODEL_THREADS", "4")))
                self.embedding = SentenceTransformer(
                    str(model_path(self.settings.embedding_model, self.settings.data_dir)),
                    device=self.settings.retrieval_device,
                    local_files_only=True,
                    trust_remote_code=False,
                )
                self.embedding.max_seq_length = 1536
            return np.asarray(
                self.embedding.encode(
                    texts, batch_size=8, normalize_embeddings=True, show_progress_bar=False
                ),
                dtype=np.float32,
            )

    def rerank(self, query, texts):
        with self.lock:
            if self.remote:
                response = self.remote.post("/rerank", json={"query": query, "texts": texts})
                response.raise_for_status()
                return np.asarray(response.json()["scores"], dtype=np.float32)
            if self.reranker is None:
                from sentence_transformers import CrossEncoder

                self.reranker = CrossEncoder(
                    str(model_path(self.settings.reranker_model, self.settings.data_dir)),
                    device=self.settings.retrieval_device,
                    max_length=1536,
                    local_files_only=True,
                    trust_remote_code=False,
                )
            return np.asarray(
                self.reranker.predict(
                    [(query, t) for t in texts], batch_size=4, show_progress_bar=False
                ),
                dtype=np.float32,
            ).reshape(-1)


@dataclass
class Hit:
    evidence: Evidence
    scores: dict

    def public(self, include_text=True):
        return {**self.evidence.public(include_text), "scores": self.scores}


class Retriever:
    def __init__(self, service, settings, models=None):
        self.service, self.db, self.settings = service, service.db, settings
        self.corpus = Corpus(service)
        self.models = models or LocalModels(settings)
        self.cache = OrderedDict()
        self.query_cache = OrderedDict()
        self.lock = threading.RLock()
        self.root = self.db.data_dir / "indexes"
        self.root.mkdir(exist_ok=True)

    def status(self):
        model = self.models.status()
        mode = self.settings.retrieval_mode
        backend = "hybrid" if mode != "lexical" and model["available"] else "bm25"
        return {
            **model,
            "backend": backend,
            "configured_mode": mode,
            "chunker": CHUNKER,
            "index_type": "FAISS IndexFlatIP" if backend == "hybrid" else None,
            "degraded": mode != "lexical" and not model["available"],
        }

    def _vectors(self, items):
        modelkey = json.dumps(self.models.fingerprint()["embedding"], sort_keys=True)
        directory = self.root / "vectors"
        directory.mkdir(exist_ok=True)
        vectors = {}
        missing = []
        for item in items:
            key = hashlib.sha256((modelkey + "\n" + item.text).encode()).hexdigest()
            path = directory / (key + ".npy")
            try:
                vec = np.load(path, allow_pickle=False)
                if vec.ndim != 1 or not np.isfinite(vec).all():
                    raise ValueError("invalid cached vector")
                vectors[item.id] = vec
            except (OSError, ValueError):
                missing.append((item, path))
        for start in range(0, len(missing), 64):
            batch = missing[start : start + 64]
            encoded = self.models.encode([i.text for i, p in batch])
            for (item, path), vector in zip(batch, encoded, strict=True):
                temporary = path.with_name(
                    path.stem + "." + __import__("uuid").uuid4().hex + ".tmp"
                )
                with temporary.open("wb") as output:
                    np.save(output, vector, allow_pickle=False)
                temporary.replace(path)
                vectors[item.id] = vector
        matrix = np.stack([vectors[i.id] for i in items]).astype(np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.maximum(norms, 1e-12)

    def search(
        self, project_id, snapshot, query, top_k=8, strategy="hybrid", rerank=True, recall_k=40
    ):
        with self.lock:
            # Eligibility is applied by Corpus before scoring or any top-k cut.
            items = self.corpus.items(project_id, snapshot)
            if not items:
                return [], {"backend": "empty", "candidates": 0, "chunker": CHUNKER}
            status = self.status()
            dense = strategy in {"dense", "hybrid"} and status["backend"] == "hybrid"
            if strategy == "dense" and not dense:
                raise Problem("稠密检索模型不可用，未执行向量检索", 503)
            if self.settings.retrieval_mode == "hybrid" and not dense:
                raise Problem("混合检索配置要求完整模型，请先准备模型", 503)
            fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "project_id": project_id,
                        "items": [
                            (i.id, hashlib.sha256(i.text.encode()).hexdigest()) for i in items
                        ],
                        "models": self.models.fingerprint(),
                        "chunker": CHUNKER,
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            cached = self.cache.get(fingerprint)
            if not cached:
                cached = {"items": items, "matrix": None, "index": None, "bm25": None}
                if dense:
                    import faiss

                    matrix = self._vectors(items)
                    index = faiss.IndexFlatIP(matrix.shape[1])
                    index.add(matrix)
                    directory = self.root / fingerprint
                    directory.mkdir(exist_ok=True)
                    faiss.write_index(index, str(directory / "vectors.faiss"))
                    cached.update(matrix=matrix, index=index)
                self.cache[fingerprint] = cached
                while len(self.cache) > 4:
                    self.cache.popitem(last=False)
                with self.db.session() as s:
                    s.merge(
                        IndexManifest(
                            id=fingerprint,
                            project_id=project_id,
                            config={
                                "models": self.models.fingerprint(),
                                "chunker": CHUNKER,
                                "backend": status["backend"],
                            },
                            chunk_count=len(items),
                            status="ready",
                        )
                    )
            # A lexical first call must not poison a subsequent dense request.
            if dense and cached["index"] is None:
                self.cache.pop(fingerprint, None)
                return self.search(project_id, snapshot, query, top_k, strategy, rerank, recall_k)
            rankings = []
            components = {i.id: {} for i in items}
            by_id = {i.id: i for i in items}
            if strategy != "dense":
                if cached["bm25"] is None:
                    cached["bm25"] = BM25Index([i.text for i in items])
                scores = cached["bm25"].score(query)
                ranking = sorted(range(len(items)), key=lambda p: (-float(scores[p]), items[p].id))
                ranking = [p for p in ranking if scores[p] > 0][:recall_k]
                rankings.append([items[p].id for p in ranking])
                for p in ranking:
                    components[items[p].id]["bm25"] = float(scores[p])
            if dense:
                query_key = hashlib.sha256(
                    (
                        json.dumps(self.models.fingerprint()["embedding"], sort_keys=True) + query
                    ).encode()
                ).hexdigest()
                if query_key not in self.query_cache:
                    self.query_cache[query_key] = self.models.encode([query])
                    while len(self.query_cache) > 128:
                        self.query_cache.popitem(last=False)
                self.query_cache.move_to_end(query_key)
                vector = self.query_cache[query_key].copy()
                vector /= np.maximum(np.linalg.norm(vector, axis=1, keepdims=True), 1e-12)
                scores, indices = cached["index"].search(vector, min(recall_k, len(items)))
                rankings.append([items[p].id for p in indices[0] if p >= 0])
                for score, p in zip(scores[0], indices[0]):
                    if p >= 0:
                        components[items[p].id]["dense"] = float(score)
            fused = rrf(rankings)
            candidates = sorted(fused, key=lambda k: (-fused[k], k))[:30]
            for key in candidates:
                components[key]["rrf"] = fused[key]
            used_rerank = bool(rerank and dense and candidates)
            if used_rerank:
                scores = self.models.rerank(query, [by_id[k].text for k in candidates])
                for key, score in zip(candidates, scores, strict=True):
                    components[key]["rerank"] = float(score)
                candidates.sort(key=lambda k: (-components[k]["rerank"], -fused[k], k))
            hits = [Hit(by_id[key], components[key]) for key in candidates[:top_k]]
            return hits, {
                "backend": "hybrid"
                if dense and strategy == "hybrid"
                else ("dense" if dense else "bm25"),
                "reranked": used_rerank,
                "index_id": fingerprint,
                "eligible": len(items),
                "candidates": len(candidates),
                "rankings": rankings,
                "chunker": CHUNKER,
                "models": self.models.fingerprint(),
                "degraded": status["degraded"],
            }


def prepare_models(settings):
    from huggingface_hub import snapshot_download

    pinned = {
        "BAAI/bge-m3": "5617a9f61b028005a4858fdac845db406aefb181",
        "BAAI/bge-reranker-v2-m3": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
    }
    outputs = []
    for model in [settings.embedding_model, settings.reranker_model]:
        if model not in pinned:
            path = model_path(model, settings.data_dir)
            if not path:
                raise Problem("自定义模型请先准备本地目录，并配置模型路径")
            outputs.append(str(path))
            continue
        target = settings.data_dir / "models" / model.split("/")[-1]
        snapshot_download(
            model,
            revision=pinned[model],
            local_dir=target,
            allow_patterns=["*.json", "*.bin", "*.safetensors", "*.model", "1_Pooling/*"],
            ignore_patterns=["onnx/*", "imgs/*"],
            max_workers=2,
        )
        (target / "zhixu-model.json").write_text(
            json.dumps({"id": model, "revision": pinned[model]})
        )
        outputs.append(str(target))
    return outputs
