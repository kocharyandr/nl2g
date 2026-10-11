#!/usr/bin/env python3
"""Синхронизация промптов агентов между кодом и Langfuse.

Источник истины — локальные fallback-шаблоны в `app/prompts/*.py`. Скрипт
сравнивает их с версиями в Langfuse под нужным label и при необходимости
заливает локальные как новую версию.

Промпты не перечислены списком, а находятся автоматически: в каждом модуле
`app/prompts/*.py` ищутся константы `*_NAME` (имя промпта в Langfuse) и парная
к ним константа с текстом (`*_FALLBACK`, `*_TEMPLATE_FALLBACK`, `*_TEMPLATE`).
Так список не устаревает при добавлении новых промптов.

Использование:

    set -a && . ./.env && set +a

    python scripts/sync_langfuse_prompts.py              # что расходится
    python scripts/sync_langfuse_prompts.py --diff       # + построчный diff
    python scripts/sync_langfuse_prompts.py --push       # залить расходящиеся
    python scripts/sync_langfuse_prompts.py --push --all # залить все

В режиме проверки код возврата 1, если найдены расхождения или промпт
отсутствует в Langfuse — годится для CI.
"""

from __future__ import annotations

import argparse
import base64
import difflib
import importlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "app" / "prompts"
TEXT_CONST_SUFFIXES = ("_FALLBACK", "_TEMPLATE_FALLBACK", "_TEMPLATE", "_PROMPT_FALLBACK")


@dataclass(slots=True)
class LocalPrompt:
    name: str
    text: str
    source: str  # "модуль.КОНСТАНТА" — чтобы было видно, откуда взят текст


def collect_local_prompts() -> list[LocalPrompt]:
    """Находит все пары (имя промпта, текст) в app/prompts/*.py."""
    found: list[LocalPrompt] = []
    orphans: list[str] = []

    for path in sorted(PROMPTS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        module = importlib.import_module(f"app.prompts.{path.stem}")
        names = {
            const: value
            for const, value in vars(module).items()
            if const.endswith("_NAME") and isinstance(value, str)
        }
        for const, prompt_name in sorted(names.items()):
            prefix = const[: -len("_NAME")]
            text_const = next(
                (f"{prefix}{suffix}" for suffix in TEXT_CONST_SUFFIXES if hasattr(module, f"{prefix}{suffix}")),
                None,
            )
            if text_const is None:
                orphans.append(f"{path.stem}.{const} ({prompt_name})")
                continue
            found.append(
                LocalPrompt(
                    name=prompt_name,
                    text=str(getattr(module, text_const)).strip(),
                    source=f"{path.stem}.{text_const}",
                )
            )

    if orphans:
        print("ВНИМАНИЕ: не найден текст промпта для констант:", file=sys.stderr)
        for item in orphans:
            print(f"  - {item}", file=sys.stderr)
        print(file=sys.stderr)

    return sorted(found, key=lambda p: p.name)


def _auth_header() -> str:
    pair = f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode()
    return "Basic " + base64.b64encode(pair).decode()


def _host() -> str:
    return (settings.langfuse_host or "http://localhost:3000").rstrip("/")


def _request(method: str, url: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", _auth_header())
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as response:
        body = response.read().decode()
    return json.loads(body) if body else {}


def fetch_remote(name: str, label: str) -> tuple[str | None, int | None]:
    """Текст и версия промпта в Langfuse; (None, None) — если промпта нет."""
    url = f"{_host()}/api/public/v2/prompts/{urllib.parse.quote(name)}?label={urllib.parse.quote(label)}"
    try:
        data = _request("GET", url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, None
        raise
    prompt = data.get("prompt")
    text = prompt if isinstance(prompt, str) else json.dumps(prompt, ensure_ascii=False)
    return text.strip(), data.get("version")


def push(name: str, text: str, label: str) -> int:
    url = f"{_host()}/api/public/v2/prompts"
    payload = {"name": name, "prompt": text, "type": "text", "labels": [label]}
    return _request("POST", url, payload).get("version", -1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--push", action="store_true", help="залить локальные версии в Langfuse")
    parser.add_argument("--all", action="store_true", help="с --push: залить все, а не только расходящиеся")
    parser.add_argument("--diff", action="store_true", help="показать построчный diff расхождений")
    parser.add_argument("--label", default=None, help="label в Langfuse (по умолчанию из LANGFUSE_PROMPT_LABEL)")
    args = parser.parse_args()

    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        print("LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY не заданы", file=sys.stderr)
        return 2

    label = args.label or settings.langfuse_prompt_label or "production"
    local_prompts = collect_local_prompts()

    print(f"Langfuse : {_host()}")
    print(f"Label    : {label}")
    print(f"Промптов в коде: {len(local_prompts)}")
    print()

    drifted: list[tuple[LocalPrompt, str | None]] = []

    for prompt in local_prompts:
        try:
            remote_text, version = fetch_remote(prompt.name, label)
        except Exception as exc:  # noqa: BLE001
            print(f"  ?  {prompt.name:42} ошибка запроса: {exc}")
            continue

        if remote_text is None:
            print(f"  +  {prompt.name:42} нет в Langfuse")
            drifted.append((prompt, None))
        elif remote_text == prompt.text:
            print(f"  =  {prompt.name:42} v{version} совпадает")
        else:
            ratio = difflib.SequenceMatcher(None, prompt.text, remote_text).ratio()
            print(f"  !  {prompt.name:42} v{version} расходится (сходство {ratio:.0%})")
            drifted.append((prompt, remote_text))

    if args.diff:
        for prompt, remote_text in drifted:
            if remote_text is None:
                continue
            print()
            print("=" * 78)
            print(f"{prompt.name}  ({prompt.source})")
            for line in difflib.unified_diff(
                remote_text.splitlines(),
                prompt.text.splitlines(),
                fromfile="langfuse",
                tofile="local",
                lineterm="",
            ):
                print(line)

    print()
    if not args.push:
        if drifted:
            print(f"Расходятся или отсутствуют: {len(drifted)}. Залить: --push")
            return 1
        print("Langfuse совпадает с кодом.")
        return 0

    to_push = local_prompts if args.all else [prompt for prompt, _ in drifted]
    if not to_push:
        print("Нечего заливать.")
        return 0

    print(f"Заливаю {len(to_push)} промпт(ов) под label '{label}':")
    failed = 0
    for prompt in to_push:
        try:
            version = push(prompt.name, prompt.text, label)
            print(f"  ✓  {prompt.name:42} → v{version}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗  {prompt.name:42} {exc}")
            failed += 1

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
