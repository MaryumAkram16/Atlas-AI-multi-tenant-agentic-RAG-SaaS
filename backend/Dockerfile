FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken

WORKDIR /app

RUN useradd --create-home --uid 10001 atlas

COPY pyproject.toml ./
COPY app ./app
RUN pip install .
# Bake the cl100k_base encoding into the image so containers never download it.
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
COPY alembic.ini ./
COPY migrations ./migrations

# Local object storage (named volume inherits this ownership).
RUN mkdir -p /data/storage && chown atlas:atlas /data/storage

USER atlas
EXPOSE 8000

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
