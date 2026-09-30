import json

from fastapi import APIRouter

from wheres_allie.api.deps import Conn, Ing

router = APIRouter()


@router.get("/nodes")
def list_nodes(conn: Conn, ing: Ing) -> list[dict]:
    home = conn.execute("SELECT json FROM home ORDER BY version DESC LIMIT 1").fetchone()
    placed = {n["id"] for n in json.loads(home["json"]).get("nodes", [])} if home else set()
    return [dict(r) | {"online": bool(r["online"]), "placed": r["id"] in placed,
                       "nearby_devices": ing.nearby_devices(r["id"])}
            for r in conn.execute("SELECT * FROM nodes ORDER BY id")]
