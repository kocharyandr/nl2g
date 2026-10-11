import requests

from .config import API_BASE, REQUEST_TIMEOUT


def fetch_session(session_id: str) -> requests.Response:
    return requests.get(
        f"{API_BASE}/sessions/{session_id}",
        timeout=REQUEST_TIMEOUT,
    )


def send_user_message(
    session_id: str,
    content: str,
    images_base64: list[str],
    csv_data: str | None = None,
    auto_validate_enabled: bool = True,
    generation_seed: int | None = None,
    no_text_mode: bool = False,
    use_sql_source: bool = False,
    sql_datasource_id: str | None = None,
) -> requests.Response:
    return requests.post(
        f"{API_BASE}/sessions/{session_id}/messages",
        json={
            "type": "message",
            "content": content,
            "images_base64": images_base64,
            "csv_data": csv_data,
            "value": None,
            "auto_validate_enabled": auto_validate_enabled,
            "generation_seed": generation_seed,
            "no_text_mode": no_text_mode,
            "use_sql_source": use_sql_source,
            "sql_datasource_id": sql_datasource_id,
        },
        timeout=REQUEST_TIMEOUT,
    )


def send_decision(
    session_id: str,
    decision: str,
    content: str = "",
    images_base64: list[str] | None = None,
) -> requests.Response:
    return requests.post(
        f"{API_BASE}/sessions/{session_id}/messages",
        json={
            "type": "decision",
            "value": decision,
            "content": content,
            "images_base64": images_base64 or [],
        },
        timeout=REQUEST_TIMEOUT,
    )


def fetch_sql_datasources() -> tuple[list[str], str]:
    """Available databases for the picker; empty list when the branch is off."""
    try:
        response = requests.get(f"{API_BASE}/sql/datasources", timeout=5)
        response.raise_for_status()
        data = response.json()
        return list(data.get("datasources") or []), data.get("default_id") or ""
    except requests.RequestException:
        return [], ""
