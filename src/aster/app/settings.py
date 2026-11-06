import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_url: str
    model_url: str
    model_name: str
    model_key: str
    access_token: str
    static_dir: Path
    retrieval_mode: str = "auto"
    embedding_model: str = "BAAI/bge-m3"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    retrieval_device: str = "cpu"
    retrieval_url: str = ""

    @classmethod
    def from_env(cls):
        def env(name, default):
            return os.getenv("ASTER_" + name, os.getenv("ZHIXU_" + name, default))

        # Preserve existing installations; use the English name for new directories.
        default_data = ".local/zhixu" if Path(".local/zhixu").exists() else ".local/aster"
        data = Path(env("DATA_DIR", default_data)).resolve()
        database_file = "zhixu.db" if (data / "zhixu.db").exists() else "aster.db"
        return cls(
            data,
            env("DATABASE_URL", f"sqlite:///{data / database_file}"),
            env("MODEL_URL", "http://127.0.0.1:8000/v1").rstrip("/"),
            env("MODEL", "auto"),
            env("MODEL_KEY", "local"),
            env("ACCESS_TOKEN", ""),
            Path(env("STATIC_DIR", str(Path(__file__).parents[1] / "static"))),
            env("RETRIEVAL_MODE", "auto"),
            env("EMBEDDING_MODEL", "BAAI/bge-m3"),
            env("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
            env("RETRIEVAL_DEVICE", "cpu"),
            env("RETRIEVAL_URL", ""),
        )
