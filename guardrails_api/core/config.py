import torch
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


class Settings(BaseSettings):
    # API
    API_VERSION: str
    API_TITLE: str
    API_DESCRIPTION: str
    PROJECT_VERSION: str

    # Model — default GLiNER2 multilingual base (good Russian support, fast on CPU).
    # Alternatives: fastino/gliner2-large-v1 (340M, more accurate),
    # hivetrace/gliner-guard-omni (legacy v1).
    MODEL_NAME: str = "fastino/gliner2-multi-v1"
    DEVICE: str = Field(default_factory=_resolve_device, validate_default=True)

    @field_validator("DEVICE", mode="before")
    @classmethod
    def _coerce_device(cls, value: str | None) -> str:
        if not value:
            return _resolve_device()
        if "cuda" in value and not torch.cuda.is_available():
            return "cpu"
        return value

    # Thresholds
    THRESHOLD_SAFETY: float = 0.2
    THRESHOLD_ADVERSARIAL: float = 0.5
    THRESHOLD_HARMFUL: float = 0.5
    THRESHOLD_INTENT: float = 0.5
    THRESHOLD_TONE: float = 0.6
    THRESHOLD_POLICY: float = 0.35

    # Reject messages (RU)
    MSG_REJECT_SAFETY: str = (
        "К сожалению, ваш запрос содержит небезопасное содержимое, "
        "и мы не можем его обработать. Пожалуйста, переформулируйте вопрос — "
        "будем рады помочь."
    )
    MSG_REJECT_ADVERSARIAL: str = (
        "Похоже, ваш запрос пытается обойти ограничения сервиса. "
        "Пожалуйста, задайте вопрос напрямую — мы постараемся помочь."
    )
    MSG_REJECT_HARMFUL: str = (
        "К сожалению, ваш запрос содержит потенциально вредоносное содержимое "
        "(например, призывы к насилию, оскорбления, опасные инструкции или "
        "раскрытие персональных данных), и мы не можем его обработать. "
        "Пожалуйста, переформулируйте вопрос корректно."
    )
    MSG_REJECT_INTENT: str = (
        "Похоже, ваш запрос направлен на обход правил сервиса. "
        "Пожалуйста, сформулируйте вопрос по существу — будем рады помочь."
    )
    MSG_REJECT_TONE: str = (
        "Ваше сообщение содержит агрессивные или манипулятивные формулировки. "
        "Давайте продолжим общение в уважительном тоне — так мы сможем вам помочь."
    )
    MSG_REJECT_POLICY: str = (
        "К сожалению, эта тема выходит за рамки тематики нашего сервиса. "
        "Будем рады помочь с вопросами по профилю сервиса."
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
