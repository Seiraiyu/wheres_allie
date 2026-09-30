def test_ws_forwards_bus_events(client):
    bus = client.app.state.bus
    with client.websocket_connect("/api/ws") as ws:
        client.portal.call(bus.publish, "node.health", {"id": "office", "online": True})
        assert ws.receive_json() == {"topic": "node.health",
                                     "data": {"id": "office", "online": True}}
    assert bus._subs == []
