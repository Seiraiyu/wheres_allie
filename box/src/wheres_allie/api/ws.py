import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws")
async def events(websocket: WebSocket) -> None:
    """Forward every bus event to the GUI as {topic, data}."""
    with websocket.app.state.bus.subscribe("") as sub:  # subscribe before accept: no lost events
        await websocket.accept()

        async def pump() -> None:
            async for topic, data in sub:
                await websocket.send_json({"topic": topic, "data": data})

        task = asyncio.create_task(pump())
        try:
            while True:
                await websocket.receive_text()  # raises on disconnect; client messages ignored
        except WebSocketDisconnect:
            pass
        finally:
            task.cancel()
