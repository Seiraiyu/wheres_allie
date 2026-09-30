from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WA_")

    data_dir: Path = Path("/data")
    mqtt_host: str = "mosquitto"
    mqtt_port: int = 1883
    mqtt_user: str = "wheres_allie"
    mqtt_pass: str
    http_port: int = 8080
    tz: str = "America/New_York"
    relay_url: str = ""
    lan_token: str = ""
    public_host: str = ""
    web_dist: Path = Path(__file__).resolve().parents[2] / "web" / "dist"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "wheres_allie.db"
