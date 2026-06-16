"""core/config.py v10"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
from cryptography.fernet import Fernet

class Settings(BaseSettings):
    supabase_url: str = Field(default="", env="SUPABASE_URL")
    supabase_key: str = Field(default="", env="SUPABASE_SERVICE_KEY")
    secret_key: str = Field(default="estrading-v10-secret-change-in-production-2026", env="SECRET_KEY")
    encryption_key: str = Field(default="", env="ENCRYPTION_KEY")
    frontend_url: str = Field(default="https://estrading-machine.vercel.app", env="FRONTEND_URL")
    env: str = Field(default="production", env="ENV")
    stripe_key: Optional[str] = Field(default=None, env="STRIPE_SECRET_KEY")
    telegram_token: Optional[str] = Field(default=None, env="TELEGRAM_BOT_TOKEN")
    sentry_dsn: Optional[str] = Field(default=None, env="SENTRY_DSN")
    redis_url: Optional[str] = Field(default=None, env="REDIS_URL")
    contact_phone: str = "+255653712466"
    contact_email: str = "estradingmachine@gmail.com"
    app_name: str = "estrading.machine"
    app_version: str = "10.0.0"

    def __init__(self, **data):
        super().__init__(**data)
        if not self.encryption_key:
            self.encryption_key = Fernet.generate_key().decode()

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
