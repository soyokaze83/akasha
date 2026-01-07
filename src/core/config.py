"""Application configuration using Pydantic Settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "akasha"
    debug: bool = False
    log_level: str = "INFO"

    # GoWA Configuration
    gowa_base_url: str = "http://whatsapp:3000"
    gowa_username: str = "user1"
    gowa_password: str = "pass1"
    gowa_webhook_secret: str = "your-secret-key"

    # LLM Configuration
    llm_provider: str = "gemini"  # Options: "gemini", "openai"
    llm_fallback_enabled: bool = True  # Enable fallback to other provider on exhaustion

    # Gemini Configuration (supports comma-separated keys for rotation)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    @property
    def gemini_api_keys(self) -> list[str]:
        """Parse comma-separated Gemini API keys into list."""
        if not self.gemini_api_key:
            return []
        return [k.strip() for k in self.gemini_api_key.split(",") if k.strip()]

    # OpenAI Configuration
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Reply Agent - Google Search Configuration
    google_search_api_key: str = ""
    google_search_engine_id: str = ""
    reply_agent_enabled: bool = True

    # Mandarin Generator - Recipients (comma-separated JIDs)
    whatsapp_recipients: str = ""

    # Mandarin Generator - Topic Selection Mode
    # Options: "free" (LLM freely chooses), "web_search" (use today's news)
    topic_selection_mode: str = "free"

    # Scheduler Configuration
    daily_passage_hour: int = 7
    daily_passage_minute: int = 0
    timezone: str = "Asia/Jakarta"

    @property
    def recipients_list(self) -> list[str]:
        """Parse comma-separated recipients into list."""
        if not self.whatsapp_recipients:
            return []
        return [r.strip() for r in self.whatsapp_recipients.split(",") if r.strip()]


settings = Settings()
