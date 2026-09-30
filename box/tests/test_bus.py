import asyncio

from wheres_allie.bus import Bus


async def test_prefix_filter_and_unsubscribe():
    bus = Bus()
    with bus.subscribe("node.") as sub:
        bus.publish("reading", {"rssi": -70})
        bus.publish("node.health", {"id": "office"})
        topic, data = await asyncio.wait_for(anext(sub), 1)
        assert (topic, data) == ("node.health", {"id": "office"})
        assert sub.queue.empty()
    bus.publish("node.health", {"id": "loft"})
    assert bus._subs == []
