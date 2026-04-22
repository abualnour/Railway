FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

# System packages + PostgreSQL 18 client
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates gnupg build-essential pkg-config \
    libcairo2-dev libpango1.0-dev libgdk-pixbuf-2.0-0 libgdk-pixbuf2.0-dev \
    libglib2.0-dev libfontconfig1-dev libfreetype6-dev libffi-dev \
    postgresql-common \
    && /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-18 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN python -m venv /opt/venv \
    && . /opt/venv/bin/activate \
    && python -m pip install --upgrade pip setuptools wheel \
    && pip install -r /app/requirements.txt

COPY . /app

ENV PATH="/opt/venv/bin:$PATH"
ENV HR_BACKUP_PG_DUMP_COMMAND="/usr/lib/postgresql/18/bin/pg_dump"

CMD gunicorn config.wsgi:application --bind 0.0.0.0:${PORT} --workers 1 --threads 2 --timeout 120