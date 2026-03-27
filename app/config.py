from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    odds_api_key: str
    collection_interval_hours: int = 6
    prediction_lead_hours: int = 2

    class Config:
        env_file = ".env"


settings = Settings()
