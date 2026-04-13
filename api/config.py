from pydantic_settings import BaseSettings


class APISettings(BaseSettings):
    database_url: str
    api_prefix: str = "/api"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = APISettings()
