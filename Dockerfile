FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1
WORKDIR /app

FROM base AS backend
RUN apt-get update && apt-get install -y curl ca-certificates && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir aws-cli
RUN curl -fsSL "https://dl.k8s.io/release/v1.30.5/bin/linux/amd64/kubectl" -o /usr/local/bin/kubectl \
    && chmod +x /usr/local/bin/kubectl
COPY . .
EXPOSE 8080
CMD ["python", "-m", "app.main"]
