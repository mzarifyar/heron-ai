FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1
WORKDIR /app

FROM base AS backend

# Detect architecture and install the right kubectl binary
RUN apt-get update && apt-get install -y curl ca-certificates && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# kubectl — auto-selects arm64 or amd64 based on build platform
RUN ARCH=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/') && \
    curl -fsSL "https://dl.k8s.io/release/v1.30.5/bin/linux/${ARCH}/kubectl" \
         -o /usr/local/bin/kubectl && \
    chmod +x /usr/local/bin/kubectl

COPY . .
EXPOSE 8080
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
