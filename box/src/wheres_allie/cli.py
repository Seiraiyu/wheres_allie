import typer
import uvicorn

from wheres_allie.api.app import create_app
from wheres_allie.config import Settings

app = typer.Typer(no_args_is_help=True, help="wheres_allie home box")


@app.callback()
def main() -> None:
    """wheres_allie home box."""


@app.command()
def serve() -> None:
    """Run the API + GUI + MQTT ingest + retention (config from WA_* env vars)."""
    uvicorn.run(create_app(), host="0.0.0.0", port=Settings().http_port)
