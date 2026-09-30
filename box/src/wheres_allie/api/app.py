import asyncio
import sqlite3
from contextlib import asynccontextmanager
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from wheres_allie import __version__, db
from wheres_allie.api import ws
from wheres_allie.api.deps import Cfg, Conn
from wheres_allie.api.routes import nodes, pets
from wheres_allie.bus import Bus
from wheres_allie.config import Settings
from wheres_allie.ingest.mqtt import Ingestor, run_ingest
from wheres_allie.retention import run_retention


class SPAStaticFiles(StaticFiles):
    """Serves web/dist; unknown non-/api, non-/mcp paths get index.html (client-side routes)."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code != 404 or path.startswith(("api", "mcp")):
                raise
            return await super().get_response("index.html", scope)


class SiteSettings(BaseModel):
    tz: str
    units: Literal["ft", "m"]
    home_name: str = Field(min_length=1, max_length=60)


def read_site_settings(conn: sqlite3.Connection, settings: Settings) -> SiteSettings:
    return SiteSettings(tz=db.get_setting(conn, "tz", settings.tz),
                        units=db.get_setting(conn, "units", "ft"),
                        home_name=db.get_setting(conn, "home_name", "Home"))


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
    app.include_router(nodes.router, prefix="/api")
    app.include_router(pets.router, prefix="/api")
    app.include_router(ws.router, prefix="/api")

    @app.get("/api/health")
    def health(request: Request) -> dict:
        relay = request.app.state.relay_status if settings.relay_url else "disabled"
        return {"ok": True, "version": __version__, "relay": relay}

    @app.get("/api/settings")
    def get_settings(conn: Conn, cfg: Cfg) -> SiteSettings:
        return read_site_settings(conn, cfg)

    @app.put("/api/settings")
    def put_settings(body: SiteSettings, conn: Conn, cfg: Cfg) -> SiteSettings:
        try:
            ZoneInfo(body.tz)
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(422, f"unknown time zone {body.tz!r}") from None
        for key, value in body.model_dump().items():
            db.set_setting(conn, key, value)
        return read_site_settings(conn, cfg)

    # Keep this mount LAST: it matches every path not claimed above (plans add /mcp before it).
    if settings.web_dist.is_dir():
        app.mount("/", SPAStaticFiles(directory=settings.web_dist, html=True), name="web")
    return app
