from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ORDER_DEADLINE: str = "10:00"

    class Config:
        env_file = ".env"


settings = Settings()
