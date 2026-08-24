from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    openai_api_key: SecretStr
    google_api_key: SecretStr
    pinecone_api_key: SecretStr
    pinecone_env: str
    pinecone_index_name: str
    pinecone_namespace: str
    model: str
    embedding_model: str
    top_k: int
    database_url: str
    # db_name: str
    # db_user: str
    # db_password: SecretStr
    # db_host: str
    # db_port: int
    # db_sslmode: str
    postgres_db: str
    postgres_user: str
    postgres_password: str
    postgres_host: str
    postgres_port: str
    secret_key: SecretStr #auth secret key
    algorithm: str #auth hashing algorithm
    access_token_expire_minutes: int = 30 #auth access token expiration time
    


settings = Settings()  # type: ignore[call-arg] # Loaded from .env file