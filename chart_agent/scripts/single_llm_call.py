import base64
import mimetypes
from pathlib import Path

import requests


# BASE_URL = "http://localhost:1234/v1"
BASE_URL = 'https://45a768cf-dd2c-4d96-9a98-7e24ce4866e5.modelrun.inference.cloud.ru/v1'
API_KEY = ""
MODEL = ""
IMAGE_PATH = str(Path(__file__).resolve().parent.parent / "app" / "graph" / "pipeline_graph.png")


def _build_data_url(image_path: str) -> str:
    path = Path(image_path)
    mime_type, _ = mimetypes.guess_type(path.name)
    if not mime_type:
        mime_type = "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def main() -> None:
    image_data_url = _build_data_url(IMAGE_PATH)
    response = requests.post(
        f"{BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": "Отвечай кратко."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": ""},
                        # {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                },
            ],
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    print(data["choices"][0]["message"]["content"])


if __name__ == "__main__":
    main()
