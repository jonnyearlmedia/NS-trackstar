FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system trackstar \
    && adduser --system --ingroup trackstar --home /app trackstar

COPY services/api/pyproject.toml /tmp/api/pyproject.toml
COPY services/api/src /tmp/api/src
COPY services/ingest/pyproject.toml /tmp/ingest/pyproject.toml
COPY services/ingest/src /tmp/ingest/src
RUN python -m pip install --no-cache-dir /tmp/api /tmp/ingest \
    && rm -rf /tmp/api /tmp/ingest

COPY --chown=trackstar:trackstar config /app/config
COPY --chown=trackstar:trackstar infra/collector_scheduler.py /app/infra/collector_scheduler.py

USER trackstar

EXPOSE 8000
CMD ["uvicorn", "ns_trackstar_api.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]

