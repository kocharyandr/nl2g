"""Скачивание весов FLUX.2 [Klein] 9B в кеш Hugging Face.

Модель gated: нужен HF_TOKEN аккаунта, принявшего лицензию Black Forest Labs.

    export HF_TOKEN=hf_...
    python download_flux_snapshot.py
"""

import os

from huggingface_hub import snapshot_download

# Итоговая (дистиллированная) модель системы — её грузит сервис инференса.
REPO_ID = os.environ.get("FLUX_MODEL_ID", "black-forest-labs/FLUX.2-klein-9B")


def main() -> None:
    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        raise SystemExit("HF_TOKEN is not set (FLUX.2-klein-9B is a gated repo)")

    path = snapshot_download(
        repo_id=REPO_ID,
        token=token,
        # The repo ships the transformer twice: sharded under transformer/ and
        # as the single-file checkpoint flux-2-klein-9b.safetensors. We keep the
        # single file (the service loads it via from_single_file) and skip the
        # 17 GB of shards; configs and the rest of the pipeline still download.
        ignore_patterns=["transformer/*.safetensors", "*.jpg", "*.png"],
    )
    print(path)


if __name__ == "__main__":
    main()
