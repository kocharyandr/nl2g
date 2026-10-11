"""Configuration for the SQL agent service.

Mirrors the style of chart_agent/app/core/config.py: pydantic-settings with
explicit env aliases and `*_safe` properties for normalised access.

The three role endpoints are separate on purpose. Each role runs behind its
own OpenAI-compatible server pinned to its own LoRA adapter (see
scripts/run_mlx_servers.sh). The service itself only speaks HTTP — it has no
MLX dependency and no knowledge of adapters.
"""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _strip_trailing_slash(value: str) -> str:
    return value.rstrip("/")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "sql_agent/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # ── Database ──────────────────────────────────────────────────────────
    # Variant A: the service returns the raw result set; aggregation for the
    # chart is decided downstream by chart_agent's existing codegen step.
    db_backend: str = Field(default="sqlite", alias="DB_BACKEND")
    db_path: str = Field(default="", alias="DB_PATH")
    db_id: str = Field(default="", alias="DB_ID")
    # Directories scanned for *.sqlite, ":"-separated. Every file found becomes
    # a datasource whose id is its filename stem, so one service can answer
    # against any database in the benchmark suites without a restart.
    datasource_roots: str = Field(default="", alias="DATASOURCE_ROOTS")
    db_statement_timeout_sec: float = Field(default=15.0, alias="DB_STATEMENT_TIMEOUT_SEC")
    db_max_rows: int = Field(default=5000, alias="DB_MAX_ROWS")

    # ── Schema profile (descriptions of tables/columns) ────────────────────
    profiles_dir: str = Field(default="", alias="PROFILES_DIR")

    # ── LLM roles (OpenAI-compatible endpoints) ───────────────────────────
    llm_api_key: str = Field(default="local-key", alias="LLM_API_KEY")
    llm_timeout_sec: float = Field(default=120.0, alias="LLM_TIMEOUT_SEC")
    llm_temperature: float = Field(default=0.0, alias="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(default=512, alias="LLM_MAX_TOKENS")

    schema_api_base: str = Field(default="http://localhost:8071/v1", alias="SCHEMA_API_BASE")
    schema_model_name: str = Field(default="default_model", alias="SCHEMA_MODEL_NAME")
    sql_api_base: str = Field(default="http://localhost:8072/v1", alias="SQL_API_BASE")
    sql_model_name: str = Field(default="default_model", alias="SQL_MODEL_NAME")
    critic_api_base: str = Field(default="http://localhost:8073/v1", alias="CRITIC_API_BASE")
    critic_model_name: str = Field(default="default_model", alias="CRITIC_MODEL_NAME")

    # ── Pipeline behaviour ────────────────────────────────────────────────
    critic_max_attempts: int = Field(default=3, alias="CRITIC_MAX_ATTEMPTS")
    use_profile: bool = Field(default=True, alias="USE_PROFILE")
    # Minimal first version answers only ok/error. Turn on to let the schema
    # agent escalate an ambiguous question back to the user.
    clarification_enabled: bool = Field(default=False, alias="CLARIFICATION_ENABLED")
    # Explanation is mandatory in the contract; this only controls whether it
    # costs an extra LLM call or is derived from the SQL agent's own reasoning.
    explanation_llm_call: bool = Field(default=True, alias="EXPLANATION_LLM_CALL")

    @property
    def db_max_rows_safe(self) -> int:
        return max(1, int(self.db_max_rows))

    @property
    def critic_max_attempts_safe(self) -> int:
        return max(1, int(self.critic_max_attempts))

    @property
    def db_statement_timeout_safe(self) -> float:
        value = float(self.db_statement_timeout_sec)
        return value if value > 0 else 15.0

    @property
    def datasource_roots_safe(self) -> list[str]:
        raw = (self.datasource_roots or "").strip()
        return [part.strip() for part in raw.split(":") if part.strip()]

    @property
    def profiles_dir_safe(self) -> str:
        return (self.profiles_dir or "").strip()

    def role_endpoint(self, role: str) -> tuple[str, str]:
        """Return (base_url, model_name) for a pipeline role."""
        mapping = {
            "schema": (self.schema_api_base, self.schema_model_name),
            "sql": (self.sql_api_base, self.sql_model_name),
            "critic": (self.critic_api_base, self.critic_model_name),
        }
        if role not in mapping:
            raise ValueError(f"unknown role '{role}', expected one of {sorted(mapping)}")
        base, model = mapping[role]
        return _strip_trailing_slash((base or "").strip()), (model or "").strip() or "default_model"


settings = Settings()
