from __future__ import annotations

import logging

from app.core.config import settings
from app.graph.state import AppState

logger = logging.getLogger(__name__)

STATE: dict[str, AppState] = {}
_redis_client = None


def _state_key(session_id: str) -> str:
    return f"{settings.state_store_redis_prefix_safe}:{session_id}"


def _get_redis_client():
    global _redis_client
    if not settings.state_store_redis_enabled:
        return None
    if _redis_client is not None:
        return _redis_client

    try:
        import redis

        _redis_client = redis.Redis.from_url(
            settings.state_store_redis_url,
            decode_responses=True,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
        )
        _redis_client.ping()
        logger.info("Redis state store connected: %s", settings.state_store_redis_url)
        return _redis_client
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis state store unavailable, fallback to memory: %s", exc)
        _redis_client = None
        return None


def _deserialize_state(raw: str) -> AppState | None:
    try:
        return AppState.model_validate_json(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to deserialize state from Redis: %s", exc)
        return None


def get_state(session_id: str) -> AppState | None:
    client = _get_redis_client()
    if client is not None:
        try:
            raw = client.get(_state_key(session_id))
            if raw:
                state = _deserialize_state(raw)
                if state is not None:
                    STATE[session_id] = state
                    return state
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis get state failed, fallback to memory: %s", exc)
    return STATE.get(session_id)


def publish_state(state: AppState) -> None:
    STATE[state.session_id] = state
    client = _get_redis_client()
    if client is None:
        return

    try:
        payload = state.model_dump_json()
        ttl = settings.state_store_redis_ttl_safe
        if ttl > 0:
            client.setex(_state_key(state.session_id), ttl, payload)
        else:
            client.set(_state_key(state.session_id), payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis publish_state failed: %s", exc)


def publish_ephemeral_status(state: AppState, status: str) -> None:
    state.ephemeral_status = status
    publish_state(state)
