import base64
import csv
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def extract_file_paths(msg: dict[str, Any] | None) -> tuple[str | None, list[str]]:
    if not msg:
        return None, []

    files = msg.get("files") or []
    if not files:
        return None, []

    csv_path: str | None = None
    image_paths: list[str] = []

    for item in files:
        path = None
        if isinstance(item, dict):
            path = item.get("path") or item.get("name")
        elif isinstance(item, str):
            path = item

        if not path:
            continue

        lower = path.lower()
        if lower.endswith(".csv"):
            csv_path = path
        elif lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")):
            image_paths.append(path)

    return csv_path, image_paths


def image_to_base64(path: str) -> str | None:
    file_path = Path(path)
    if not file_path.exists():
        return None
    raw = file_path.read_bytes()
    return base64.b64encode(raw).decode("utf-8")


def read_csv_text(path: str) -> str | None:
    csv_file = Path(path)
    if not csv_file.exists():
        return None

    try:
        return csv_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return csv_file.read_text(encoding="cp1251")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed reading CSV text: %s", exc)
            return None
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed reading CSV text: %s", exc)
        return None


def csv_to_prompt_context(path: str) -> str:
    csv_file = Path(path)
    if not csv_file.exists():
        return "CSV файл прикреплен, но не найден локально."

    try:
        with csv_file.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except UnicodeDecodeError:
        with csv_file.open("r", encoding="cp1251", newline="") as f:
            reader = csv.reader(f)
            rows = list(reader)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed reading CSV: %s", exc)
        return f"CSV файл прикреплен, но не прочитан: {exc}"

    if not rows:
        return "CSV файл пустой."

    headers = rows[0]
    preview_rows = rows[1:6]

    lines = [
        f"CSV: {csv_file.name}",
        f"Колонки: {', '.join(headers) if headers else 'не определены'}",
        "Превью первых строк:",
    ]

    if not preview_rows:
        lines.append("(нет строк данных)")
    else:
        for idx, row in enumerate(preview_rows, start=1):
            lines.append(f"{idx}. {row}")

    return "\n".join(lines)
