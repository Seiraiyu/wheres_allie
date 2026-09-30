import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from wheres_allie.api.deps import Conn, Ing

router = APIRouter()


class PetIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    species: str = "dog"


class TagIn(BaseModel):
    ibeacon_id: str = Field(min_length=3)
    motion_ibeacon_id: str | None = None


def _pets(conn: sqlite3.Connection) -> list[dict]:
    pets = {r["id"]: dict(r) | {"tags": []} for r in conn.execute("SELECT * FROM pets ORDER BY id")}
    for t in conn.execute("SELECT * FROM tags ORDER BY id"):
        pets[t["pet_id"]]["tags"].append(dict(t))
    return list(pets.values())


def _pet(conn: sqlite3.Connection, pet_id: int) -> dict:
    for p in _pets(conn):
        if p["id"] == pet_id:
            return p
    raise HTTPException(404, "pet not found")


@router.get("/pets")
def list_pets(conn: Conn) -> list[dict]:
    return _pets(conn)


@router.post("/pets")
def create_pet(body: PetIn, conn: Conn) -> dict:
    try:
        cur = conn.execute("INSERT INTO pets (name, species) VALUES (?, ?)",
                           (body.name, body.species))
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"a pet named {body.name!r} already exists") from None
    return _pet(conn, cur.lastrowid)


@router.post("/pets/{pet_id}/tags")
def add_tag(pet_id: int, body: TagIn, conn: Conn, ing: Ing) -> dict:
    _pet(conn, pet_id)
    try:
        conn.execute("INSERT INTO tags (pet_id, ibeacon_id, motion_ibeacon_id) VALUES (?, ?, ?)",
                     (pet_id, body.ibeacon_id, body.motion_ibeacon_id))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "that iBeacon id is already registered") from None
    ing.reload_tags()
    return _pet(conn, pet_id)


@router.get("/tags/candidates")
def tag_candidates(ing: Ing) -> list[dict]:
    return ing.candidates()
