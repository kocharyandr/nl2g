from typing import Any


def awaiting_from_payload(payload: dict[str, Any]) -> bool:
    # Use the explicit flag from the API; fall back to stage inference for compatibility.
    explicit = payload.get("show_approve_cancel")
    if explicit is not None:
        return bool(explicit)
    return payload.get("current_stage") in {"chart_review", "plot_rendering"}


_SILENT_STAGES = {"plot_rendering", "image_generation"}


def assistant_text(payload: dict[str, Any]) -> str:
    # Suppress text when a chart or generated image is being delivered
    stage = payload.get("current_stage")
    artefacts = payload.get("artefacts") or {}
    has_chart = bool((artefacts.get("plot") or {}).get("image_base64"))
    has_image = bool((artefacts.get("image") or {}).get("image_base64"))
    if stage in _SILENT_STAGES and (has_chart or has_image):
        return ""

    assistant_message = payload.get("assistant_message") or ""
    text = str(assistant_message).strip()
    return text or "(пустой ответ от сервера)"


def chart_markdown_from_payload(payload: dict[str, Any]) -> str | None:
    artefacts = payload.get("artefacts") or {}
    image_artefact = artefacts.get("image") or {}
    image_b64 = image_artefact.get("image_base64")
    mime = image_artefact.get("mime_type") or "image/png"
    if image_b64:
        return f"![image](data:{mime};base64,{image_b64})"

    chart = artefacts.get("chart") or artefacts.get("plot") or {}
    image_b64 = chart.get("image_base64")
    if not image_b64:
        return None

    mime = chart.get("mime_type") or "image/png"
    return f"![chart](data:{mime};base64,{image_b64})"


def sql_source_markdown(payload: dict[str, Any]) -> str | None:
    """Render the query behind a chart built from database data.

    Not a nicety: a chart drawn from rows the user never saw is uncheckable
    unless the query that produced them is on screen.
    """
    artefacts = payload.get("artefacts") or {}
    info = (artefacts.get("data") or {}).get("sql_source") or {}
    if not info.get("used"):
        return None

    parts: list[str] = []
    explanation = str(info.get("explanation") or "").strip()
    if explanation:
        parts.append(explanation)

    row_count = info.get("row_count") or 0
    caption = f"строк: {row_count}"
    if info.get("truncated"):
        caption += " — выборка обрезана по лимиту, уточните условия отбора"
    parts.append(caption)

    sql = str(info.get("sql") or "").strip()
    block = "\n".join(f"<small>{p}</small>" for p in parts)
    if sql:
        block += f"\n\n<details><summary>SQL-запрос</summary>\n\n```sql\n{sql}\n```\n\n</details>"
    return block
