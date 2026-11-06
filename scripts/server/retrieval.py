"""Optional loopback-only GPU worker for the existing encoder and reranker.

Run in an existing CUDA Python. The web app can retain its CPU dependencies.
Input is text, output is vectors/scores; corpus authorization remains in the app.
"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import inspect
import json
import os
from pathlib import Path
import threading


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=".local/metabolomics/retrieval-worker.json")
    parser.add_argument("--device", default="cuda:1")
    parser.add_argument("--port", type=int, default=8767)
    args = parser.parse_args()
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    import numpy as np
    from sentence_transformers import SentenceTransformer, CrossEncoder

    config = json.loads(Path(args.config).read_text())
    lock = threading.RLock()

    def options(factory):
        supported = inspect.signature(factory).parameters
        value = {"device": args.device}
        if "local_files_only" in supported:
            value["local_files_only"] = True
        if "trust_remote_code" in supported:
            value["trust_remote_code"] = False
        return value

    encoder = SentenceTransformer(config["embedding"], **options(SentenceTransformer))
    encoder.max_seq_length = 1536
    reranker = CrossEncoder(config["reranker"], max_length=1536, **options(CrossEncoder))
    if args.device.startswith("cuda"):
        encoder.half()
        reranker.model.half()

    def score_activation(logits):
        return reranker.default_activation_function(logits.float())

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send_json(self, status, value):
            data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path != "/health":
                self.send_json(404, {"error": "not found"})
                return
            self.send_json(
                200,
                {
                    "fingerprint": config["fingerprint"],
                    "device": args.device,
                    "precision": "float16 weights / float32 score activation"
                    if args.device.startswith("cuda")
                    else "float32",
                },
            )

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 4 * 1024 * 1024:
                    raise ValueError("invalid request size")
                body = json.loads(self.rfile.read(length))
                texts = body.get("texts")
                if (
                    not isinstance(texts, list)
                    or not 1 <= len(texts) <= 1024
                    or not all(isinstance(t, str) and len(t) <= 100000 for t in texts)
                ):
                    raise ValueError("invalid texts")
                with lock:
                    if self.path == "/encode":
                        vectors = encoder.encode(
                            texts, batch_size=4, normalize_embeddings=True, show_progress_bar=False
                        )
                        result = {"vectors": np.asarray(vectors, dtype=np.float32).tolist()}
                    elif self.path == "/rerank":
                        query = body.get("query")
                        if not isinstance(query, str) or len(query) > 4000:
                            raise ValueError("invalid query")
                        scores = reranker.predict(
                            [(query, text) for text in texts],
                            batch_size=4,
                            show_progress_bar=False,
                            activation_fct=score_activation,
                        )
                        result = {
                            "scores": np.asarray(scores, dtype=np.float32).reshape(-1).tolist()
                        }
                    else:
                        self.send_json(404, {"error": "not found"})
                        return
                self.send_json(200, result)
            except (ValueError, KeyError) as error:
                self.send_json(400, {"error": str(error)})
            except Exception as error:
                self.send_json(500, {"error": type(error).__name__ + ": " + str(error)[:200]})

    print(f"Retrieval worker http://127.0.0.1:{args.port} {args.device}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
