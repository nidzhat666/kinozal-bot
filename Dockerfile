FROM python:3.12-slim

RUN apt-get update && apt-get install -y curl bash && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && ln -s /root/.local/bin/uv /usr/local/bin/uv \
    && curl -1sLf 'https://artifacts-cli.infisical.com/setup.deb.sh' | bash \
    && apt-get update && apt-get install -y infisical \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

COPY pyproject.toml uv.lock ./

RUN uv sync --frozen --no-install-project

COPY . .

WORKDIR /usr/src/app/src
ENV PYTHONPATH=/usr/src/app/src

CMD ["uv", "run", "uvicorn", "bot.main:app", "--host", "0.0.0.0", "--port", "8000"]
