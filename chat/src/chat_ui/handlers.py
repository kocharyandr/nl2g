import logging
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import gradio as gr

from .api_client import fetch_session, send_decision, send_user_message
from .file_utils import (
    extract_file_paths,
    image_to_base64,
    read_csv_text,
)
from .response_utils import (
    assistant_text,
    awaiting_from_payload,
    chart_markdown_from_payload,
    sql_source_markdown,
)

logger = logging.getLogger(__name__)
APPROVE_TEXT_ALIASES = {"подтвердить", "подтверждаю", "approve", "ok", "yes", "да"}

_CSV_ICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" '
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round" style="flex-shrink:0">'
    '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
    '<polyline points="14 2 14 8 20 8"/>'
    '<line x1="16" y1="13" x2="8" y2="13"/>'
    '<line x1="16" y1="17" x2="8" y2="17"/>'
    '<polyline points="10 9 9 9 8 9"/>'
    '</svg>'
)

_CHIP_STYLE = (
    "display:inline-flex;align-items:center;gap:5px;"
    "background:rgba(8,145,178,0.09);border:1px solid rgba(8,145,178,0.28);"
    "color:#0e7490;border-radius:8px;padding:3px 9px 3px 7px;"
    "font-size:11.5px;font-weight:500;line-height:1.5;"
    "white-space:nowrap;cursor:default;user-select:none;"
    "max-width:260px;overflow:hidden;text-overflow:ellipsis;"
)


def _csv_chip(filename: str) -> str:
    label = filename if len(filename) <= 30 else filename[:27] + "…"
    # data-copy-skip and aria-hidden tell the clipboard override JS to exclude this chip
    return (
        f'<span data-copy-skip="1" aria-hidden="true" title="{filename}" style="{_CHIP_STYLE}">'
        f'{_CSV_ICON_SVG}{label}</span>'
    )


STATUS_POLL_INTERVAL_SEC = 0.5
TYPEWRITER_CHARS_PER_TICK = 3
TYPEWRITER_TICK_SEC = 0.07

# (keyword_fragment, icon) — first match wins
_STATUS_ICONS: list[tuple[str, str]] = [
    ("думаю",           "🧠"),
    ("разбираюсь",      "🧠"),
    ("понял",           "🧠"),
    ("читаю",           "📋"),
    ("изучаю",          "📋"),
    ("извлекаю",        "📋"),
    ("подбираю",        "📋"),
    ("проверяю",        "🔍"),
    ("оцениваю",        "🔍"),
    ("данные выгляд",   "🔍"),
    ("пишу код",        "💻"),
    ("переписываю",     "💻"),
    ("исправляю",       "🔧"),
    ("нашёл",           "🔧"),
    ("что-то пошло",    "🔧"),
    ("запускаю",        "⚙️"),
    ("строю",           "📊"),
    ("начинаю строить", "📊"),
    ("рисую",           "📊"),
    ("таблица обработ", "📊"),
    ("нейросеть",       "🎨"),
    ("генерирую",       "🎨"),
    ("формулирую",      "✍️"),
    ("запрос готов",    "✍️"),
    ("взял изображени", "🖼️"),
    ("принял",          "💬"),
    ("сервис занят",    "⏳"),
    ("жду",             "⏳"),
    ("запомнил",        "💾"),
    ("обновляю памят",  "💾"),
]

SEED_RE = re.compile(
    r"(?:^|\s)(?:seed|сид)\s*(?:[:=]\s*|\s+)(-?\d+)",
    re.IGNORECASE,
)


def approve_btn_update(awaiting: bool):
    return gr.update(visible=bool(awaiting), interactive=bool(awaiting))


def cancel_btn_update(awaiting: bool):
    return gr.update(visible=bool(awaiting), interactive=bool(awaiting))


def _get_status_icon(status_text: str) -> str:
    text_lower = (status_text or "").lower()
    for keyword, icon in _STATUS_ICONS:
        if keyword in text_lower:
            return icon
    return "⏳"


_SPINNER_SVG = (
    '<svg width="14" height="14" viewBox="0 0 14 14" fill="none" '
    'xmlns="http://www.w3.org/2000/svg" '
    'style="animation:spin 0.85s linear infinite;flex-shrink:0;color:#0e7490">'
    '<circle cx="7" cy="7" r="5.5" stroke="currentColor" stroke-width="1.6" stroke-opacity="0.18"/>'
    '<path d="M 7 1.5 A 5.5 5.5 0 0 1 12.5 7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>'
    '</svg>'
)


def _status_line(display_text: str, icon: str, fully_shown: bool) -> str:
    if fully_shown:
        cursor = "<span style='animation:blink 1.2s step-end infinite;margin-left:1px'>▋</span>"
    else:
        cursor = "<span style='margin-left:1px'>▋</span>"
    return (
        f'<span style="display:inline-flex;align-items:center;gap:6px;opacity:0.78">'
        f'{_SPINNER_SVG}'
        f'<span style="display:inline-block;animation:pulse 1.8s ease-in-out infinite;'
        f'font-size:12px;line-height:1">{icon}</span>'
        f'<span>{display_text}</span>'
        f'{cursor}'
        f'</span>'
    )


def _fetch_ephemeral_status(session_id: str) -> str | None:
    try:
        resp = fetch_session(session_id)
        if resp.status_code != 200:
            return None
        payload = resp.json()
        status = payload.get("ephemeral_status")
        return status.strip() if isinstance(status, str) and status.strip() else None
    except Exception:  # noqa: BLE001
        return None


def ensure_session(session_id: str | None) -> tuple[str | None, str | None]:
    if session_id:
        return session_id, None

    return str(uuid.uuid4()), None


def _extract_seed(text: str) -> tuple[str, int | None]:
    if not text:
        return text, None
    match = SEED_RE.search(text)
    if not match:
        return text, None
    seed_text = match.group(1)
    try:
        seed = int(seed_text)
    except ValueError:
        seed = None
    cleaned = (text[: match.start()] + " " + text[match.end() :]).strip()
    return cleaned, seed


def send_message(
    message: dict[str, Any] | None,
    history: list[dict[str, str]] | None,
    session_id: str | None,
    awaiting: bool,
    auto_validate_enabled: bool,
    no_text_mode: bool = False,
    use_sql_source: bool = False,
    sql_datasource: str | None = None,
):
    history = history or []
    text = (message or {}).get("text", "").strip()
    csv_path, image_paths = extract_file_paths(message or {})
    csv_data = read_csv_text(csv_path) if csv_path else None

    if csv_path:
        if not text:
            text = "Построй график по загруженной таблице."
    text, generation_seed = _extract_seed(text)

    if not text and not image_paths:
        return history, session_id, awaiting, gr.MultimodalTextbox(value=None), approve_btn_update(awaiting), cancel_btn_update(awaiting)

    sid, err = ensure_session(session_id)
    if not sid:
        history.append({"role": "assistant", "content": f"Ошибка: {err or 'session not created'}"})
        return history, session_id, False, gr.MultimodalTextbox(value=None), approve_btn_update(False), cancel_btn_update(False)

    user_label = text if text else "(изображение)"
    if csv_path:
        chip = _csv_chip(Path(csv_path).name)
        user_label = f'{chip}<br><span style="display:block;margin-top:4px">{user_label}</span>'
    history.append({"role": "user", "content": user_label})
    history.append({"role": "assistant", "content": "."})
    yield history, sid, False, gr.MultimodalTextbox(value=None), approve_btn_update(False), cancel_btn_update(False)

    result_holder: list[Any] = [None]

    def run_request():
        try:
            images_b64 = [img for img in (image_to_base64(p) for p in image_paths) if img]
            if awaiting:
                normalized_text = (text or "").strip().lower()
                if normalized_text in APPROVE_TEXT_ALIASES and not images_b64:
                    response = send_decision(sid, "approve")
                else:
                    response = send_decision(
                        sid,
                        "edit",
                        content=text,
                        images_base64=images_b64,
                    )
            else:
                response = send_user_message(
                    sid,
                    text,
                    images_b64,
                    csv_data=csv_data,
                    auto_validate_enabled=bool(auto_validate_enabled),
                    generation_seed=generation_seed,
                    no_text_mode=bool(no_text_mode),
                    use_sql_source=bool(use_sql_source),
                    sql_datasource_id=(sql_datasource or "").strip() or None,
                )
            result_holder[0] = response
        except Exception as exc:  # noqa: BLE001
            result_holder[0] = exc

    thread = threading.Thread(target=run_request, daemon=True)
    thread.start()

    last_poll_ts = 0.0
    current_status = "Принял, разбираюсь..."
    shown_chars = 0

    while thread.is_alive():
        now = time.monotonic()
        if now - last_poll_ts >= STATUS_POLL_INTERVAL_SEC:
            polled_status = _fetch_ephemeral_status(sid)
            if polled_status and polled_status != current_status:
                current_status = polled_status
                shown_chars = 0
            last_poll_ts = now

        if shown_chars < len(current_status):
            shown_chars = min(shown_chars + TYPEWRITER_CHARS_PER_TICK, len(current_status))
            tick = TYPEWRITER_TICK_SEC
        else:
            tick = STATUS_POLL_INTERVAL_SEC

        icon = _get_status_icon(current_status)
        fully_shown = shown_chars >= len(current_status)
        history[-1]["content"] = _status_line(current_status[:shown_chars], icon, fully_shown)
        yield history, sid, False, gr.MultimodalTextbox(value=None), approve_btn_update(False), cancel_btn_update(False)
        time.sleep(tick)

    result = result_holder[0]
    if isinstance(result, Exception):
        logger.exception("message request failed: %s", result)
        history[-1]["content"] = f"Ошибка: {result}"
        yield history, sid, False, gr.MultimodalTextbox(value=None), approve_btn_update(False), cancel_btn_update(False)
        return

    if result.status_code != 200:
        try:
            detail = result.json().get("detail", result.text)
        except Exception:  # noqa: BLE001
            detail = result.text
        history[-1]["content"] = f"Ошибка API ({result.status_code}): {detail}"
        yield history, sid, False, gr.MultimodalTextbox(value=None), approve_btn_update(False), cancel_btn_update(False)
        return

    payload = result.json()
    assistant = assistant_text(payload)
    waiting_for_user = awaiting_from_payload(payload)
    chart_md = chart_markdown_from_payload(payload)

    if assistant:
        for i in range(1, len(assistant) + 1):
            history[-1]["content"] = assistant[:i]
            yield history, sid, waiting_for_user, gr.MultimodalTextbox(value=None), approve_btn_update(waiting_for_user), cancel_btn_update(waiting_for_user)
            time.sleep(0.01)
        history[-1]["content"] = assistant
    else:
        # No text — remove the placeholder bubble added before the request
        history.pop()

    if chart_md:
        history.append({"role": "assistant", "content": chart_md})

    # The query goes right under the chart it produced: numbers from a database
    # the user cannot see are only trustworthy if the query is visible.
    sql_md = sql_source_markdown(payload)
    if sql_md:
        history.append({"role": "assistant", "content": sql_md})

    yield history, sid, waiting_for_user, gr.MultimodalTextbox(value=None), approve_btn_update(waiting_for_user), cancel_btn_update(waiting_for_user)


def approve(
    history: list[dict[str, str]] | None,
    session_id: str | None,
):
    history = history or []
    if not session_id:
        history.append({"role": "assistant", "content": "Сначала отправьте сообщение, чтобы создать сессию."})
        return history, session_id, False, approve_btn_update(False), cancel_btn_update(False)

    status_idx = None
    history.append({"role": "assistant", "content": "."})
    status_idx = len(history) - 1
    yield history, session_id, False, approve_btn_update(False), cancel_btn_update(False)

    result_holder: list[Any] = [None]

    def run_request():
        try:
            result_holder[0] = send_decision(session_id, "approve")
        except Exception as exc:  # noqa: BLE001
            result_holder[0] = exc

    thread = threading.Thread(target=run_request, daemon=True)
    thread.start()

    last_poll_ts = 0.0
    current_status = "Принял подтверждение..."
    shown_chars = 0

    while thread.is_alive():
        now = time.monotonic()
        if now - last_poll_ts >= STATUS_POLL_INTERVAL_SEC:
            polled_status = _fetch_ephemeral_status(session_id)
            if polled_status and polled_status != current_status:
                current_status = polled_status
                shown_chars = 0
            last_poll_ts = now

        if shown_chars < len(current_status):
            shown_chars = min(shown_chars + TYPEWRITER_CHARS_PER_TICK, len(current_status))
            tick = TYPEWRITER_TICK_SEC
        else:
            tick = STATUS_POLL_INTERVAL_SEC

        if status_idx is not None:
            icon = _get_status_icon(current_status)
            fully_shown = shown_chars >= len(current_status)
            history[status_idx]["content"] = _status_line(current_status[:shown_chars], icon, fully_shown)
        yield history, session_id, False, approve_btn_update(False), cancel_btn_update(False)
        time.sleep(tick)

    result = result_holder[0]
    if isinstance(result, Exception):
        logger.exception("approve request failed: %s", result)
        if status_idx is not None:
            history[status_idx]["content"] = f"Ошибка: {result}"
        yield history, session_id, False, approve_btn_update(False), cancel_btn_update(False)
        return

    if result.status_code != 200:
        try:
            detail = result.json().get("detail", result.text)
        except Exception:  # noqa: BLE001
            detail = result.text
        if status_idx is not None:
            history[status_idx]["content"] = f"Ошибка API ({result.status_code}): {detail}"
        yield history, session_id, False, approve_btn_update(False), cancel_btn_update(False)
        return

    payload = result.json()
    waiting_for_user = awaiting_from_payload(payload)
    if status_idx is not None and 0 <= status_idx < len(history):
        history.pop(status_idx)

    yield history, session_id, waiting_for_user, approve_btn_update(waiting_for_user), cancel_btn_update(waiting_for_user)


def cancel(
    history: list[dict[str, str]] | None,
    session_id: str | None,
):
    history = history or []
    if not session_id:
        return history, session_id, False, approve_btn_update(False), cancel_btn_update(False)

    try:
        result = send_decision(session_id, "cancel")
    except Exception as exc:  # noqa: BLE001
        logger.exception("cancel request failed: %s", exc)
        return history, session_id, False, approve_btn_update(False), cancel_btn_update(False)

    if result.status_code != 200:
        logger.warning("cancel returned status=%s", result.status_code)
        return history, session_id, False, approve_btn_update(False), cancel_btn_update(False)

    payload = result.json()
    assistant = assistant_text(payload)
    if assistant:
        history.append({"role": "assistant", "content": assistant})

    return history, session_id, False, approve_btn_update(False), cancel_btn_update(False)
