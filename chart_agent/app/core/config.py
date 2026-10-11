from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _strip_trailing_slash(value: str) -> str:
    return value.rstrip("/")

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "chart_agent/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    chart_render_max_retries: int = Field(default=3, alias="CHART_RENDER_MAX_RETRIES")
    table_planner_max_retries: int = Field(default=2, alias="TABLE_PLANNER_MAX_RETRIES")
    summary_history_max_len: int = Field(default=20, alias="SUMMARY_HISTORY_MAX_LEN")
    summary_trigger_min_messages: int = Field(default=3, alias="SUMMARY_TRIGGER_MIN_MESSAGES")
    openai_api_base: str = Field(default="", alias="OPENAI_API_BASE")
    openai_api_key: str = Field(default="local-key", alias="OPENAI_API_KEY")
    openai_model_name: str = Field(default="", alias="OPENAI_MODEL_NAME")
    edit_service_url: str = Field(default="", alias="EDIT_SERVICE_URL")
    diffusion_model_name: str = Field(default="qwen", alias="DIFFUSION_MODEL_NAME")
    diffusion_host: str = Field(default="localhost", alias="DIFFUSION_HOST")
    diffusion_port: int = Field(default=8001, alias="DIFFUSION_PORT")
    diffusion_timeout_sec: float = Field(default=120.0, alias="DIFFUSION_TIMEOUT_SEC")
    edit_use_stub: bool = Field(default=True, alias="EDIT_USE_STUB")
    image_auto_validation_enabled: bool = Field(
        default=True,
        alias="IMAGE_AUTO_VALIDATION_ENABLED",
    )
    image_auto_validation_iters: int = Field(
        default=3,
        alias="IMAGE_AUTO_VALIDATION_ITERS",
    )
    image_validation_pass_threshold: float = Field(
        default=0.85,
        alias="IMAGE_VALIDATION_PASS_THRESHOLD",
    )

    llm_json_output_enabled: bool = Field(default=False, alias="LLM_JSON_OUTPUT_ENABLED")
    llm_disable_reasoning: bool = Field(default=False, alias="LLM_DISABLE_REASONING")

    langfuse_enabled: bool = Field(default=False, alias="LANGFUSE_ENABLED")
    langfuse_prompts_enabled: bool = Field(default=False, alias="LANGFUSE_PROMPTS_ENABLED")
    langfuse_public_key: str = Field(default="", alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field(default="", alias="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field(default="http://localhost:3000", alias="LANGFUSE_HOST")
    langfuse_prompt_label: str = Field(default="production", alias="LANGFUSE_PROMPT_LABEL")

    # ── Guardrails (GLiNER2 service) ──
    guardrails_enabled: bool = Field(default=False, alias="GUARDRAILS_ENABLED")
    guardrails_safety_enabled: bool = Field(default=True, alias="GUARDRAILS_SAFETY_ENABLED")
    guardrails_intent_routing_enabled: bool = Field(default=True, alias="GUARDRAILS_INTENT_ROUTING_ENABLED")
    guardrails_host: str = Field(default="guardrails-api", alias="GUARDRAILS_HOST")
    guardrails_port: int = Field(default=8000, alias="GUARDRAILS_PORT")
    guardrails_api_version: str = Field(default="/api/v1", alias="GUARDRAILS_API_VERSION")
    guardrails_timeout_sec: float = Field(default=10.0, alias="GUARDRAILS_TIMEOUT_SEC")
    guardrails_confidence_threshold: float = Field(default=0.6, alias="GUARDRAILS_CONFIDENCE_THRESHOLD")
    guardrails_fail_open: bool = Field(default=True, alias="GUARDRAILS_FAIL_OPEN")

    # ── SQL agent (NL2SQL data source) ──
    # Third data source alongside user text and uploaded CSV. Disabled by
    # default: with the flag off the system behaves exactly as before.
    sql_agent_enabled: bool = Field(default=False, alias="SQL_AGENT_ENABLED")
    sql_agent_url: str = Field(default="", alias="SQL_AGENT_URL")
    sql_agent_timeout_sec: float = Field(default=120.0, alias="SQL_AGENT_TIMEOUT_SEC")
    sql_agent_max_rows: int = Field(default=5000, alias="SQL_AGENT_MAX_ROWS")
    # Which database of the ones sql_agent registered to query. Empty means
    # the service's own default.
    sql_agent_datasource_id: str = Field(default="", alias="SQL_AGENT_DATASOURCE_ID")
    # Which database to query. Empty means the SQL service's own default, so
    # the orchestrator does not have to know the catalogue.
    sql_agent_datasource_id: str = Field(default="", alias="SQL_AGENT_DATASOURCE_ID")
    # Route database questions by an explicit UI toggle rather than by intent
    # classification. Keeps the first version's correctness independent of
    # classifier accuracy; flip on once the label is tuned.
    sql_agent_intent_routing_enabled: bool = Field(
        default=False, alias="SQL_AGENT_INTENT_ROUTING_ENABLED"
    )

    state_store_redis_enabled: bool = Field(default=False, alias="STATE_STORE_REDIS_ENABLED")
    state_store_redis_url: str = Field(
        default="redis://localhost:6379/0",
        alias="STATE_STORE_REDIS_URL",
    )
    state_store_redis_prefix: str = Field(default="chart_agent:state", alias="STATE_STORE_REDIS_PREFIX")
    state_store_redis_ttl_sec: int = Field(default=0, alias="STATE_STORE_REDIS_TTL_SEC")

    code_executor_url: str = Field(default="", alias="CODE_EXECUTOR_URL")

    @property
    def code_executor_url_safe(self) -> str:
        return (self.code_executor_url or "").strip()

    @property
    def chart_render_max_retries_safe(self) -> int:
        return max(1, self.chart_render_max_retries)

    @property
    def table_planner_max_retries_safe(self) -> int:
        return max(1, int(self.table_planner_max_retries))

    @property
    def summary_history_max_len_safe(self) -> int:
        return max(1, self.summary_history_max_len)

    @property
    def summary_trigger_min_messages_safe(self) -> int:
        return max(1, self.summary_trigger_min_messages)

    @property
    def openai_base_safe(self) -> str:
        return (self.openai_api_base or "").strip() or "http://localhost:8001/v1"

    @property
    def openai_model_safe(self) -> str:
        return (self.openai_model_name or "").strip()

    @property
    def edit_service_url_safe(self) -> str:
        explicit_url = (self.edit_service_url or "").strip()
        if explicit_url:
            return _strip_trailing_slash(explicit_url)
        return f"http://{self.diffusion_host_safe}:{self.diffusion_port_safe}/edit"

    @property
    def diffusion_model_name_safe(self) -> str:
        return (self.diffusion_model_name or "").strip().lower() or "qwen"

    @property
    def diffusion_host_safe(self) -> str:
        return (self.diffusion_host or "").strip() or "localhost"

    @property
    def diffusion_port_safe(self) -> int:
        return int(self.diffusion_port) if int(self.diffusion_port) > 0 else 8001

    @property
    def diffusion_timeout_safe(self) -> float:
        return float(self.diffusion_timeout_sec) if float(self.diffusion_timeout_sec) > 0 else 120.0

    @property
    def image_auto_validation_iters_safe(self) -> int:
        return max(1, int(self.image_auto_validation_iters))

    @property
    def image_validation_pass_threshold_safe(self) -> float:
        return max(0.0, min(1.0, float(self.image_validation_pass_threshold)))

    @property
    def state_store_redis_prefix_safe(self) -> str:
        return (self.state_store_redis_prefix or "").strip() or "chart_agent:state"

    @property
    def state_store_redis_ttl_safe(self) -> int:
        value = int(self.state_store_redis_ttl_sec)
        return value if value > 0 else 0


    @property
    def sql_agent_url_safe(self) -> str:
        return _strip_trailing_slash((self.sql_agent_url or "").strip())

    @property
    def sql_agent_datasource_id_safe(self) -> str:
        return (self.sql_agent_datasource_id or "").strip()

    @property
    def sql_agent_max_rows_safe(self) -> int:
        return max(1, int(self.sql_agent_max_rows))

    @property
    def sql_agent_datasource_safe(self) -> str:
        return (self.sql_agent_datasource_id or "").strip()

    @property
    def sql_agent_timeout_safe(self) -> float:
        value = float(self.sql_agent_timeout_sec)
        return value if value > 0 else 120.0


settings = Settings()
