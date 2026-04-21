from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    odds_api_key: str = ""
    oddalerts_api_key: str = ""
    collection_interval_hours: int = 6
    prediction_lead_hours: int = 2
    spread_model_version: str = "1.0"   # version string for spread_v1 model
    ou_model_version: str = "1.0"       # version string for ou_v1 model
    api_football_key: str = ""
    openweathermap_key: str = ""
    ml_lambda_enabled: bool = False     # enable XGBoost λ regressor for spreads
    bully_xg_overlay_enabled: bool = True

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
