import sqlite3
from typing import Annotated

from fastapi import Depends, Request

from wheres_allie.bus import Bus
from wheres_allie.config import Settings
from wheres_allie.ingest.mqtt import Ingestor


def get_conn(request: Request) -> sqlite3.Connection:
    return request.app.state.conn


def get_bus(request: Request) -> Bus:
    return request.app.state.bus


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_ingestor(request: Request) -> Ingestor:
    return request.app.state.ingestor


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]
Cfg = Annotated[Settings, Depends(get_settings)]
Ing = Annotated[Ingestor, Depends(get_ingestor)]
