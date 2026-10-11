"""Регрессия: большой результат не должен вешать исполнитель кода.

`multiprocessing.Queue` живёт поверх пайпа с буфером 64 КБ. Если родитель
сначала делает join(), а очередь не вычитана, ребёнок блокируется на записи,
родитель — на ожидании ребёнка, и всё упирается в таймаут. Base64 картинки
переходит 64 КБ примерно на 48-килобайтном PNG — то есть на любом чуть более
детальном графике.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code_executor"))

from executor import execute_chart_code  # noqa: E402


SCATTER = (
    "fig, ax = plt.subplots(figsize=(10, 6), dpi=110)\n"
    "rng = np.random.default_rng(0)\n"
    "ax.scatter(rng.random({n}), rng.random({n}), s=3)\n"
)


@pytest.mark.parametrize("points", [50, 2000, 20000])
def test_payload_above_pipe_buffer_does_not_deadlock(points):
    """2000 точек дают ровно ~64 КБ base64 — прежняя версия здесь вставала."""
    image_b64 = execute_chart_code(SCATTER.format(n=points), {}, timeout=20.0)
    assert image_b64
    assert image_b64.startswith("iVBOR")  # PNG


def test_large_payload_is_returned_intact():
    image_b64 = execute_chart_code(SCATTER.format(n=20000), {}, timeout=20.0)
    assert len(image_b64) > 200_000, "крупная картинка должна доходить целиком"


def test_timeout_still_fires_on_genuinely_slow_code():
    with pytest.raises(TimeoutError):
        execute_chart_code(
            "fig, ax = plt.subplots()\nwhile True:\n    pass\n", {}, timeout=2.0
        )
