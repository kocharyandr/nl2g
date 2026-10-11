# Сервис инференса диффузии (`/edit`)

HTTP-сервис генеративного редактирования изображений. Запускается на отдельном
GPU-хосте и вызывается оркестратором [chart_agent](../chart_agent/) на шаге
`image_generation` (`EDIT_SERVICE_URL=http://<host>:8888/edit`).

## Модели

| `model` в запросе | Веса | LoRA |
| --- | --- | --- |
| `flux` (основная) | `black-forest-labs/FLUX.2-klein-9B` — дистиллированная, 4 шага | `lora/flux2_klein_chart_edit_rank16_step2000/` (в репозитории) |
| `qwen` (сравнение) | `ovedrive/Qwen-Image-Edit-2511-4bit` | `lightx2v/Qwen-Image-Edit-2511-Lightning` (с HF) |

В памяти держится ровно одна модель; при смене `model` предыдущая выгружается.

### LoRA-адаптер

`lora/flux2_klein_chart_edit_rank16_step2000/pytorch_lora_weights.safetensors` (53 МБ),
эксперимент `exp_1_rank16`, чекпоинт на шаге 2000.

Задаёт модели ограничение на сохранение аналитической корректности графика при
визуальном редактировании: правки должны быть минорными и не искажать данные.
Trigger words не используются.

Обучался на **недистиллированной** `black-forest-labs/FLUX.2-klein-base-9B`: дистилляция
меняет характер восстановления изображения из шума и размер шагов, из-за чего обучение
адаптера на дистиллированной версии нестабильно. Применяется при этом к целевой
дистиллированной `FLUX.2-klein-9B`, которую и грузит сервис. Тренировался DreamBooth-скриптом
[Flux2 diffusers trainer](https://github.com/huggingface/diffusers/blob/main/examples/dreambooth/README_flux2.md).

| Параметр обучения | Значение |
| --- | --- |
| Ранг LoRA | 16 (сравнивались 16 / 32 / 64) |
| Выбранный шаг | 2000 (чекпоинты каждые 400, максимум 2500) |
| Точность | bf16 |
| Оптимизатор | AdamW 8-bit |
| Learning rate | 1e-4, константный планировщик с прогревом |
| Шаги прогрева | 150 |
| Размер батча | 2, аккумуляция градиентов 2 |
| LoRA dropout | 0.05 |
| Guidance scale | 1.0 |

Чекпоинт выбран на валидации по SSIM (структурное сходство) и LPIPS (перцептивное) в
связке с недистиллированной базовой моделью; после этой точки метрики не улучшались —
признак переобучения. Итоговое влияние адаптера оценивалось отдельно методикой
LLM-as-a-judge (п.3.6 ВКР).

Ручное использование вне сервиса:

```python
from diffusers import Flux2KleinPipeline
import torch

pipe = Flux2KleinPipeline.from_pretrained(
    "black-forest-labs/FLUX.2-klein-9B", torch_dtype=torch.bfloat16
).to("cuda")
pipe.load_lora_weights(
    "lora/flux2_klein_chart_edit_rank16_step2000",
    weight_name="pytorch_lora_weights.safetensors",
)
```

Лицензия адаптера наследует лицензию базовой модели.

## Веса FLUX

Репозиторий gated — нужен HF-токен аккаунта, принявшего лицензию Black Forest Labs.
Веса (~18 ГБ) в папку не входят, они скачиваются в кеш HF, который монтируется в контейнер:

```bash
export HF_TOKEN=hf_...
python download_flux_snapshot.py   # либо ничего не делать: веса скачаются при первом /edit
```

## Запуск

Нужен NVIDIA GPU (валидировалось на L4 24 ГБ) и NVIDIA Container Toolkit.

```bash
export HF_TOKEN=hf_...
export HF_CACHE_DIR=$HOME/.cache/huggingface   # опционально
docker compose up --build
```

Сервис: `http://localhost:8888` (порт меняется через `HOST_PORT`).

## API

**POST /edit** (multipart) → PNG

| Поле | Описание |
| --- | --- |
| `image_0`, `image_1`, … | входные изображения (порядок по индексу; одиночное поле `image` тоже принимается) |
| `prompt` | промпт редактирования (уже улучшенный PromptEnhancer'ом со стороны агента) |
| `model` | `flux` (по умолчанию `qwen`) |
| `num_inference_steps` | по умолчанию 4 для `flux`, 50 для `qwen` |
| `guidance_scale` | только ветка `flux`, по умолчанию 1.0 |
| `negative_prompt`, `num_images_per_prompt` | только ветка `qwen` |
| `seed` | фиксация генератора для воспроизводимости |
| `true_cfg_scale` | принимается и логируется, но в текущем коде не применяется |

Результат приводится к размеру первого входного изображения.

**GET /health** — статус и какая модель сейчас в памяти.

## Переменные окружения

| Переменная | По умолчанию |
| --- | --- |
| `FLUX_MODEL_ID` | `black-forest-labs/FLUX.2-klein-9B` |
| `FLUX_LORA_DIR` | `lora/flux2_klein_chart_edit_rank16_step2000` (пусто/несуществующий путь → базовая модель без адаптера) |
| `FLUX_LORA_WEIGHT_NAME` | `pytorch_lora_weights.safetensors` |
| `MODEL_ID`, `LORA_REPO`, `LORA_WEIGHT_NAME` | ветка `qwen` |
| `HF_TOKEN` | обязателен для gated-весов |
| `HOST_PORT` | `8888` |
| `SAVE_INPUT_ARTIFACTS`, `ARTIFACTS_DIR` | сохранение входных картинок для отладки |
