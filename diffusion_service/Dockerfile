FROM nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev \
    libgl1-mesa-glx libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app

RUN python -m pip install --no-cache-dir --upgrade pip 
# && \
#     for i in 1 2 3; do \
#       python -m pip install --no-cache-dir \
#         --default-timeout=1000 \
#         --retries=20 \
#         torch torchvision \
#         --index-url https://download.pytorch.org/whl/cu128 && break; \
#       echo "PyTorch install failed, retry $i/3 in 15s..."; \
#       sleep 15; \
#     done

# RUN pip3 install torchvision 
RUN pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cu128

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY download_flux_snapshot.py .
COPY lora ./lora

CMD ["sh", "-c", "exec python -m uvicorn app:app --host 0.0.0.0 --port 8001"]
