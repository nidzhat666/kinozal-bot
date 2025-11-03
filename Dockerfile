FROM python:3.12-slim

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && ln -s /root/.local/bin/uv /usr/local/bin/uv

WORKDIR /usr/src/app

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-install-project

COPY . .

WORKDIR /usr/src/app/src
ENV PYTHONPATH=/usr/src/app/src

CMD ["uv", "run", "python", "bot/main.py"]
