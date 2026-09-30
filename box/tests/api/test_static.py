from fastapi.testclient import TestClient

from wheres_allie.api.app import create_app


def test_serves_spa_with_client_side_routes(settings, conn, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    settings.web_dist = dist
    with TestClient(create_app(settings, conn=conn, start_background=False)) as c:
        assert c.get("/").text == "<div id=root></div>"
        assert c.get("/nodes").text == "<div id=root></div>"
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert c.get("/api/health").json()["ok"] is True
        assert c.get("/api/nope").status_code == 404
        assert c.get("/mcp/nope").status_code == 404


def test_no_dist_means_api_only(client):
    assert client.get("/").status_code == 404
