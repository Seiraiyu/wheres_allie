def test_defaults(client):
    assert client.get("/api/settings").json() == {
        "tz": "America/New_York", "units": "ft", "home_name": "Home"}


def test_put_then_get(client):
    body = {"tz": "America/Chicago", "units": "m", "home_name": "Stonely house"}
    assert client.put("/api/settings", json=body).json() == body
    assert client.get("/api/settings").json() == body


def test_rejects_bad_values(client):
    assert client.put("/api/settings", json={"tz": "Mars/Base", "units": "m",
                                             "home_name": "x"}).status_code == 422
    assert client.put("/api/settings", json={"tz": "UTC", "units": "yards",
                                             "home_name": "x"}).status_code == 422
