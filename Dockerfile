# syntax=docker/dockerfile:1
FROM python:3.12-slim

# uv from Astral: https://docs.astral.sh/uv/
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_PYTHON_DOWNLOADS=never
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# libvips system library required by the pyvips bindings for image manipulation.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libvips42 \
 && rm -rf /var/lib/apt/lists/*

# Install the application dependencies (and the project itself, from src/) from the lockfile.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

EXPOSE 8000

# Run the FastAPI IIIF image server via uvicorn.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
