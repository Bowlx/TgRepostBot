from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    bot_token: str
    linkedin_client_id: str
    linkedin_client_secret: str
    linkedin_redirect_uri: str
    google_translate_api_key: str
    database_path: str = "data/bot.db"
    default_source_lang: str = "ru"
    default_target_lang: str = "en"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


def get_settings() -> Settings:
    return Settings()
