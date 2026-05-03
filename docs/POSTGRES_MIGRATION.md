# PostgreSQL Migration Guide

This project now prefers PostgreSQL whenever `DATABASE_URL` is set.

## 1. Reconnect this copied folder to Git

This folder currently has no `.git` directory, so it is not connected to GitHub yet.

If this folder should track the same remote repository again:

```powershell
cd C:\Users\AbuNour\Desktop\NourAxis
git init
git branch -M main
git remote add origin <your-github-repo-url>
git fetch origin
git checkout -t origin/main
```

If Git says files already exist and block checkout, stop there and compare this copy with the original repository before forcing anything.

## 2. Point local development to PostgreSQL

Set one of these approaches before running Django:

### Option A: One connection string

```powershell
$env:DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:5432/nouraxis_local"
```

### Option B: Separate PostgreSQL variables

```powershell
$env:POSTGRES_DB="nouraxis_local"
$env:POSTGRES_USER="postgres"
$env:POSTGRES_PASSWORD="postgres"
$env:POSTGRES_HOST="127.0.0.1"
$env:POSTGRES_PORT="5432"
```

## 3. Create schema in PostgreSQL

Run migrations against PostgreSQL:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

## 4. Copy data from SQLite into PostgreSQL

Export from SQLite:

```powershell
.\.venv\Scripts\python.exe manage.py dumpdata --natural-foreign --natural-primary --exclude contenttypes --exclude auth.permission --indent 2 > data.json
```

Then import into PostgreSQL after `DATABASE_URL` points to PostgreSQL:

```powershell
.\.venv\Scripts\python.exe manage.py loaddata data.json
```

## 5. Verify you are using PostgreSQL

```powershell
.\.venv\Scripts\python.exe manage.py shell -c "from django.db import connection; print(connection.vendor); print(connection.settings_dict['NAME'])"
```

Expected vendor:

```text
postgresql
```

## 6. Deploy later with the same database style

Your `render.yaml` already uses `DATABASE_URL` from the managed PostgreSQL database, so once local testing is working, deployment will use the same database family.
