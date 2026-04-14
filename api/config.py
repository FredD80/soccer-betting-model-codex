from pydantic_settings import BaseSettings


class APISettings(BaseSettings):
    database_url: str
    api_prefix: str = "/api"
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = APISettings()
