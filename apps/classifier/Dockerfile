FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TZ=America/Anchorage
ENV PIP_ROOT_USER_ACTION=ignore
ENV PYTORCH_CPU_INDEX_URL=https://download.pytorch.org/whl/cpu
ENV PADDLE_CPU_INDEX_URL=https://www.paddlepaddle.org.cn/packages/stable/cpu/
ENV PYTHONPATH=/app:/app/src

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    jq \
    file \
    libmagic1 \
    libgl1 \
    libglib2.0-0 \
    tesseract-ocr \
    poppler-utils \
    libreoffice \
    pandoc \
    fonts-dejavu \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY apps/classifier/requirements.txt /app/apps/classifier/requirements.txt

RUN python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install --no-cache-dir --index-url ${PYTORCH_CPU_INDEX_URL} torch torchvision && \
    python -m pip install --no-cache-dir --extra-index-url ${PADDLE_CPU_INDEX_URL} paddlepaddle && \
    python -m pip install --no-cache-dir -r /app/apps/classifier/requirements.txt

COPY apps /app/apps
COPY packages /app/packages
COPY src /app/src
COPY config /app/config

CMD ["python", "/app/apps/classifier/classify-to-obsidian.py"]
