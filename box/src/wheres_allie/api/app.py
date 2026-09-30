import asyncio
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from wheres_allie import __version__, db
from wheres_allie.bus import Bus
from wheres_allie.config import Settings
from wheres_allie.ingest.mqtt import Ingestor, run_ingest
from wheres_allie.retention import run_retention


def create_app(settings: Settings | None = None, conn: sqlite3.Connection | None = None,
               start_background: bool = True) -> FastAPI:
    settings = settings or Settings()
    if conn is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        conn = db.connect(settings.db_path)
    db.migrate(conn)
    bus = Bus()
    ingestor = Ingestor(conn, bus)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        tasks = []
        if start_background:  # later plans append their background tasks here
            tasks = [asyncio.create_task(run_ingest(settings, conn, bus, ingestor)),
                     asyncio.create_task(run_retention(conn))]
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(title="wheres_allie", version=__version__, lifespan=lifespan)
    app.state.settings, app.state.conn, app.state.bus = settings, conn, bus
    app.state.ingestor = ingestor
    app.state.relay_status = "offline"  # set by relaylink (plan 06)

    @app.get("/api/health")
    def health(request: Request) -> dict:
        relay = request.app.state.relay_status if settings.relay_url else "disabled"
        return {"ok": True, "version": __version__, "relay": relay}

    return app
