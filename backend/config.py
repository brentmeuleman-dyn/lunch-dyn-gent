from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SMTP_HOST: str = "smtp.office365.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    FROM_EMAIL: str = ""
    SHOP_EMAIL: str = ""
    ORDER_DEADLINE: str = "10:00"

    class Config:
        env_file = ".env"


settings = Settings()
