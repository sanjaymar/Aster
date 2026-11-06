from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from aster.domain.models import Workspace


class Database:
    def __init__(self, url, data_dir):
        self.url = url
        self.data_dir = Path(data_dir)
        from aster.storage.paths import prepare

        prepare(self.data_dir)
        options = (
            {"connect_args": {"check_same_thread": False, "timeout": 30}}
            if url.startswith("sqlite:")
            else {"pool_pre_ping": True}
        )
        self.engine = create_engine(url, **options)
        if self.engine.dialect.name == "sqlite":

            @event.listens_for(self.engine, "connect")
            def configure(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA busy_timeout=30000")

        self.factory = sessionmaker(self.engine, expire_on_commit=False)

    def migrate(self):
        migrations = Path(__file__).parent / "migrations"
        cfg = Config()
        cfg.set_main_option("script_location", str(migrations))
        cfg.set_main_option("sqlalchemy.url", self.url.replace("%", "%%"))
        with self.engine.begin() as connection:
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "head")
        with self.session() as session:
            if not session.get(Workspace, "personal"):
                session.add(Workspace(id="personal", name="个人空间"))

    @contextmanager
    def session(self):
        with self.factory() as session:
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise
