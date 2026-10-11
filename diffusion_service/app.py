import asyncio
import gc
import io
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

# До первого обращения к CUDA: меньше фрагментации при смене больших моделей.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from PIL import Image

from diffusers import Flux2KleinPipeline, Flux2Transformer2DModel, QwenImageEditPlusPipeline
# from qwen_pipline_orig import QwenImageEditPlusPipeline
from transformers import Qwen2_5_VLForConditionalGeneration
from diffusers import AutoencoderKLQwenImage
from diffusers import QwenImageTransformer2DModel
from huggingface_hub import login


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HF_TOKEN = os.environ.get("HF_TOKEN", "")
if HF_TOKEN:
    login(HF_TOKEN)

def _best_device() -> str:
    """cuda on the GPU host, mps on Apple Silicon, cpu as a last resort.

    The service was written for a CUDA host; on a Mac the same pipelines run
    on Metal. bfloat16 is supported by MPS on M-series, so dtypes stay as-is.
    """
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


pipe_qwen = None
flux_pipe = None
# Какая модель сейчас в памяти (ровно одна из двух или None до первого /edit).
loaded_model: str | None = None
_pipeline_lock = asyncio.Lock()

# Итоговая модель системы (см. п.3.3 ВКР): FLUX.2 [Klein] 9B, дистиллированная (4 шага).
FLUX_MODEL_ID = os.environ.get("FLUX_MODEL_ID", "black-forest-labs/FLUX.2-klein-9B")
# LoRA-адаптер для редактирования графиков: rank 16, checkpoint 2000 (п.3.6 ВКР).
# Обучался на недистиллированной black-forest-labs/FLUX.2-klein-base-9B.
FLUX_LORA_DIR = os.environ.get(
    "FLUX_LORA_DIR", "lora/flux2_klein_chart_edit_rank16_step2000"
)
FLUX_LORA_WEIGHT_NAME = os.environ.get(
    "FLUX_LORA_WEIGHT_NAME", "pytorch_lora_weights.safetensors"
)

# Второй вариант модели, использовался в сравнении (Qwen-Local).
MODEL_ID = os.environ.get("MODEL_ID", "ovedrive/Qwen-Image-Edit-2511-4bit")
LORA_REPO = os.environ.get("LORA_REPO", "lightx2v/Qwen-Image-Edit-2511-Lightning")
LORA_WEIGHT_NAME = os.environ.get(
    "LORA_WEIGHT_NAME",
    "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-fp32.safetensors",
)
PORT = int(os.environ.get("PORT", "8001"))


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


# В Docker: SAVE_INPUT_ARTIFACTS=1 и том на ARTIFACTS_DIR (по умолчанию /artifacts).
SAVE_INPUT_ARTIFACTS = _env_bool("SAVE_INPUT_ARTIFACTS", False)
ARTIFACTS_DIR = os.environ.get("ARTIFACTS_DIR") or os.path.join(os.getcwd(), "artifacts")


def init_qwen_model():
    global pipe_qwen

    logger.info("Loading Qwen model %s...", MODEL_ID)

    kwargs = dict(
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
    )

    text_encoder = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        MODEL_ID,
        subfolder="text_encoder",
        trust_remote_code=True,
        device_map="cpu",
        torch_dtype=torch.bfloat16,
    )

    vae = AutoencoderKLQwenImage.from_pretrained(
        MODEL_ID,
        subfolder="vae",
        trust_remote_code=True,
        device_map="cpu",
        torch_dtype=torch.bfloat16,
    )


    transformer = QwenImageTransformer2DModel.from_pretrained(
        MODEL_ID,
        subfolder="transformer",
        trust_remote_code=True,
        device_map="cpu",
        torch_dtype=torch.bfloat16,
    )

    # if HF_TOKEN:
    #     kwargs["token"] = HF_TOKEN

    # pipe = QwenImageEditPlusPipeline.from_pretrained(MODEL_ID, **kwargs)
    pipe_qwen = QwenImageEditPlusPipeline.from_pretrained(
        MODEL_ID,
        text_encoder=text_encoder,
        vae=vae,
        transformer=transformer,
        # device_map="cpu",
        torch_dtype=torch.bfloat16,
    )
    if LORA_REPO and LORA_WEIGHT_NAME:
        logger.info("Loading LoRA %s / %s", LORA_REPO, LORA_WEIGHT_NAME)
        pipe_qwen.load_lora_weights(
            LORA_REPO, weight_name=LORA_WEIGHT_NAME, token=HF_TOKEN or None
        )

    # pipe_qwen.reset_device_map()
    # pipe_qwen.enable_model_cpu_offload()
    logger.info("Move Qwen model to %s", _best_device())
    pipe_qwen.to(_best_device())
    logger.info("Qwen model ready.")


def _try_detach_pipeline_gpu(pipe) -> None:
    """Снимает offload-хуки accelerate/diffusers, чтобы тензоры на GPU отпустились до del."""
    if pipe is None:
        return
    fn = getattr(pipe, "maybe_free_model_hooks", None)
    if callable(fn):
        try:
            fn()
        except Exception as ex:
            logger.warning("maybe_free_model_hooks failed: %s", ex)


def _release_cuda_memory() -> None:
    # Несколько проходов: циклы ссылок на модули/тензоры иногда отпускаются не с первого раза.
    for _ in range(3):
        gc.collect()
    if not torch.cuda.is_available():
        return
    try:
        torch.cuda.ipc_collect()
    except Exception:
        pass
    for d in range(torch.cuda.device_count()):
        with torch.cuda.device(d):
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
    gc.collect()


def unload_qwen_model():
    global pipe_qwen
    if pipe_qwen is None:
        return
    logger.info("Unloading Qwen model")
    _try_detach_pipeline_gpu(pipe_qwen)
    del pipe_qwen
    pipe_qwen = None
    _release_cuda_memory()


def unload_flux_model():
    global flux_pipe
    if flux_pipe is None:
        return
    logger.info("Unloading Flux model")
    _try_detach_pipeline_gpu(flux_pipe)
    del flux_pipe
    flux_pipe = None
    _release_cuda_memory()


def ensure_active_model(model: str) -> None:
    """Держит в памяти только одну модель; при смене model выгружает предыдущую."""
    global loaded_model
    if model not in ("qwen", "flux"):
        raise ValueError(model)
    if loaded_model == model:
        return
    if loaded_model == "qwen":
        unload_qwen_model()
    elif loaded_model == "flux":
        unload_flux_model()
    loaded_model = None
    _release_cuda_memory()
    if model == "qwen":
        init_qwen_model()
    else:
        init_flux_model()
    loaded_model = model


def _find_single_file() -> str | None:
    """Path to the single-file transformer checkpoint, if configured or cached.

    The repo ships the transformer twice — sharded and as one file. When the
    single file is already in the HF cache (or FLUX_SINGLE_FILE points at it),
    the 17 GB of shards are not needed at all.
    """
    explicit = os.environ.get("FLUX_SINGLE_FILE", "").strip()
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    try:
        from huggingface_hub import try_to_load_from_cache
        cached = try_to_load_from_cache(FLUX_MODEL_ID, "flux-2-klein-9b.safetensors")
        if isinstance(cached, str) and os.path.isfile(cached):
            return cached
    except Exception as ex:  # noqa: BLE001
        logger.debug("single-file cache probe failed: %s", ex)
    return None


def init_flux_model():
    global flux_pipe
    logger.info("Loading Flux model %s...", FLUX_MODEL_ID)

    single_file = _find_single_file()
    transformer = None
    if single_file:
        logger.info("Loading transformer from single file: %s", single_file)
        transformer = Flux2Transformer2DModel.from_single_file(
            single_file,
            config=FLUX_MODEL_ID,
            subfolder="transformer",
            torch_dtype=torch.bfloat16,
            token=HF_TOKEN or None,
        )

    flux_pipe = Flux2KleinPipeline.from_pretrained(
        FLUX_MODEL_ID,
        transformer=transformer,
        torch_dtype=torch.bfloat16,
        token=HF_TOKEN or None,
    )

    lora_dir = Path(FLUX_LORA_DIR)
    if not lora_dir.is_absolute():
        lora_dir = Path(__file__).resolve().parent / lora_dir
    lora_path = lora_dir / FLUX_LORA_WEIGHT_NAME
    if lora_path.is_file():
        logger.info("Loading Flux LoRA: %s", lora_path)
        flux_pipe.load_lora_weights(str(lora_dir), weight_name=FLUX_LORA_WEIGHT_NAME)
    else:
        logger.warning("Flux LoRA not found at %s, running base model", lora_path)

    # flux_pipe.enable_model_cpu_offload()
    flux_pipe.to(_best_device())
    logger.info("Flux model ready.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Модели грузятся при первом POST /edit и при смене поля model в форме.
    yield
    # cleanup if needed
    pass


app = FastAPI(title="Qwen Image Edit API", lifespan=lifespan)


def _parse_int(s: str | None, default: int | None = 0) -> int | None:
    if s is None or (isinstance(s, str) and s.strip() == ""):
        return default
    try:
        return int(s)
    except ValueError:
        return default


def _parse_float(s: str | None, default: float) -> float:
    if s is None or s.strip() == "":
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _resize_to_match_with_padding(images: list[Image.Image], target_size: tuple[int, int]) -> list[Image.Image]:
    """Приводит все изображения кроме первого к размеру target_size с чёрным паддингом (letterbox)."""
    if len(images) <= 1:
        return images
    target_w, target_h = target_size
    result = [images[0]]
    for img in images[1:]:
        w, h = img.size
        if (w, h) == (target_w, target_h):
            result.append(img.copy())
            continue
        scale = min(target_w / w, target_h / h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        padded = Image.new("RGB", (target_w, target_h), (0, 0, 0))
        paste_x = (target_w - new_w) // 2
        paste_y = (target_h - new_h) // 2
        padded.paste(resized, (paste_x, paste_y))
        result.append(padded)
    return result


def _save_input_artifacts(pil_images: list[Image.Image], model: str, prompt: str) -> None:
    if not SAVE_INPUT_ARTIFACTS or not pil_images:
        return
    try:
        base = Path(ARTIFACTS_DIR)
        base.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        run_id = f"{ts}_{uuid.uuid4().hex[:8]}"
        run_dir = base / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        for i, pil in enumerate(pil_images):
            pil.save(run_dir / f"input_{i:02d}.png")
        meta = {
            "model": model,
            "prompt": (prompt or "")[:2000],
            "n_inputs": len(pil_images),
        }
        (run_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Saved %s input images under %s", len(pil_images), run_dir)
    except OSError as e:
        logger.warning("Could not save input artifacts: %s", e)


@app.post("/edit", response_class=Response)
async def edit_image(request: Request):
    form = await request.form()

    model = (form.get("model") or "qwen").strip().lower()
    if model not in ("qwen", "flux"):
        raise HTTPException(
            status_code=400,
            detail="`model` must be `qwen` or `flux`",
        )

    # Параметры (как в check_qwen.ipynb)
    prompt = form.get("prompt")
    num_inference_steps = form.get("num_inference_steps", "4")
    num_images_per_prompt = form.get("num_images_per_prompt", "1")
    negative_prompt = form.get("negative_prompt", "")
    true_cfg_scale = form.get("true_cfg_scale", "4.0")
    seed = form.get("seed", 42)

    # Логи для отладки multipart-запроса
    try:
        keys = list(form.keys())
    except Exception:
        keys = []
    client = getattr(request, "client", None)
    logger.info(
        "POST /edit model=%s from=%s keys=%s prompt_len=%s seed=%s steps=%s cfg=%s num_images_per_prompt=%s",
        model,
        getattr(client, "host", None) if client else None,
        keys,
        len(prompt) if isinstance(prompt, str) else None,
        seed,
        num_inference_steps,
        true_cfg_scale,
        num_images_per_prompt,
    )

    if not prompt:
        raise HTTPException(status_code=400, detail="`prompt` is required")

    # Собираем картинки строго по тегам: image_0, image_1, ...
    # Это восстанавливает порядок (multipart иногда приходит не в нужном порядке).
    indexed_files: dict[int, UploadFile] = {}
    plain_files: list[UploadFile] = []
    for key, val in form.multi_items():
        # Multipart parsing в FastAPI/Starlette иногда даёт не тот тип, поэтому используем duck-typing.
        is_upload_like = hasattr(val, "filename") and hasattr(val, "read")
        logger.info(
            "multipart item key=%s type=%s upload_like=%s filename=%s content_type=%s",
            key,
            type(val),
            is_upload_like,
            getattr(val, "filename", None),
            getattr(val, "content_type", None),
        )
        if not is_upload_like:
            continue

        upload = val
        if key == "image":
            plain_files.append(upload)
            continue
        if key.startswith("image_"):
            idx_str = key[len("image_") :]
            if idx_str.isdigit():
                indexed_files[int(idx_str)] = upload
            else:
                plain_files.append(upload)

    uploads: list[UploadFile]
    if indexed_files:
        uploads = [indexed_files[i] for i in sorted(indexed_files.keys())]
    else:
        uploads = plain_files

    logger.info(
        "Parsed uploads: indexed=%s plain=%s using_count=%s",
        sorted(indexed_files.keys()) if indexed_files else [],
        len(plain_files),
        len(uploads),
    )

    if not uploads:
        raise HTTPException(status_code=400, detail="At least one image is required (use image_0, image_1, ...)")

    pil_images: list[Image.Image] = []
    for upload in uploads:
        content_type = upload.content_type or ""
        if "image" not in content_type and not upload.filename:
            raise HTTPException(status_code=400, detail="Expected image files in `image_0`/`image_1`/...")
        try:
            data = await upload.read()
            logger.info(
                "Read image: filename=%s content_type=%s bytes=%s",
                upload.filename,
                content_type,
                len(data),
            )
            pil = Image.open(io.BytesIO(data)).convert("RGB")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid image: {e}") from e
        pil_images.append(pil)

    if len(pil_images) > 1:
        pil_images = _resize_to_match_with_padding(pil_images, pil_images[0].size)

    _save_input_artifacts(pil_images, model, prompt if isinstance(prompt, str) else "")

    default_steps = 50 if model == "qwen" else 4
    steps = _parse_int(num_inference_steps, default_steps)
    num_images = max(1, _parse_int(num_images_per_prompt, 1) or 1)
    cfg = _parse_float(true_cfg_scale, 4.0)
    guidance_scale = _parse_float(form.get("guidance_scale", "1"), 1.0)
    neg = str(negative_prompt).strip() or None
    seed_val = _parse_int(str(seed), None) if seed else None

    try:
        async with _pipeline_lock:
            ensure_active_model(model)
            with torch.inference_mode():
                if model == "flux":
                    if flux_pipe is None:
                        raise HTTPException(status_code=503, detail="Flux model not loaded")
                    if torch.cuda.is_available():
                        gen_device = "cuda"
                    elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                        gen_device = "mps"
                    else:
                        gen_device = "cpu"
                    generator = torch.Generator(device=gen_device)
                    if seed_val is not None:
                        generator.manual_seed(seed_val)
                    out = flux_pipe(
                        prompt=prompt,
                        image=pil_images,
                        num_inference_steps=steps,
                        guidance_scale=guidance_scale,
                        generator=generator,
                    )
                else:
                    if pipe_qwen is None:
                        raise HTTPException(status_code=503, detail="Qwen model not loaded")
                    kwargs = {
                        "image": pil_images,
                        "prompt": prompt,
                        "num_inference_steps": steps,
                        # "true_cfg_scale": cfg,
                        "num_images_per_prompt": num_images,
                    }
                    if neg:
                        kwargs["negative_prompt"] = neg
                    if seed_val is not None:
                        kwargs["generator"] = torch.manual_seed(seed_val)
                    out = pipe_qwen(**kwargs)
            result_pil = out.images[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Inference failed")
        raise HTTPException(status_code=500, detail=str(e)) from e

    target_w, target_h = pil_images[0].size
    if result_pil.size != (target_w, target_h):
        result_pil = result_pil.resize((target_w, target_h), Image.LANCZOS)

    buf = io.BytesIO()
    result_pil.save(buf, format="PNG")
    buf.seek(0)
    return Response(content=buf.read(), media_type="image/png")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "active_model": loaded_model,
        "qwen_loaded": pipe_qwen is not None,
        "flux_loaded": flux_pipe is not None,
        "save_input_artifacts": SAVE_INPUT_ARTIFACTS,
        "artifacts_dir": ARTIFACTS_DIR,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
