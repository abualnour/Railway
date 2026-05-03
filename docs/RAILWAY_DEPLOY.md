# Railway Deployment Guide

This project is prepared to run on Railway as the active deployment platform.

## What Was Prepared

- Platform-neutral Gunicorn startup through `gunicorn.conf.py`
- `Procfile` for Railway web process detection
- `.python-version` to pin Railway builds to Python 3.12 for better compatibility with the PDF stack
- Dynamic `PORT` binding for Railway
- Automatic support for:
  - `RAILWAY_PUBLIC_DOMAIN`
  - `DJANGO_PUBLIC_BASE_URL`
  - `DJANGO_ALLOWED_HOSTS`
  - `DJANGO_CSRF_TRUSTED_ORIGINS`
- Railway volume-aware media and backup paths
## Railway Service Setup

Create these services in Railway:

1. Web service for this repository
2. PostgreSQL database service
3. Optional volume for persistent media and backup files

## Recommended Railway Variables

Set these on the web service:

```env
DJANGO_SECRET_KEY=your-long-random-secret
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
DJANGO_CSRF_TRUSTED_ORIGINS=
DJANGO_PUBLIC_BASE_URL=https://your-public-domain.up.railway.app
DATABASE_URL=<use Railway PostgreSQL connection>
```

If you attach a Railway volume, also set:

```env
RAILWAY_VOLUME_MOUNT_PATH=/data
DJANGO_MEDIA_ROOT=/data/media
HR_BACKUP_ROOT=/data/backups
```

For full PostgreSQL backup ZIP support, Railway also needs the PostgreSQL client tool (`pg_dump`).
Railway is configured in [railway.toml](C:\Users\AbuNour\Desktop\NourAxis\railway.toml) to build with Nixpacks, so the active [nixpacks.toml](C:\Users\AbuNour\Desktop\NourAxis\nixpacks.toml) file is what requests the PostgreSQL client during deploy.
Railway is currently using Railpack with `mise`, so the committed [.python-version](C:\Users\AbuNour\Desktop\NourAxis\.python-version) file is the important Python-version source for deploys.
If you prefer an explicit override, you can also set:

```env
HR_BACKUP_PG_DUMP_COMMAND=pg_dump
```

If you do not attach a volume, the app will still run, but uploaded media and backup files will be ephemeral.

## Build And Start Commands

Use these Railway commands:

Build command:

```bash
bash build.sh
```

Pre-deploy command:

```bash
python manage.py migrate --no-input
```

Start command:

```bash
gunicorn config.wsgi:application -c gunicorn.conf.py
```

## Login And CSRF Notes

If login fails after deploy, check these first:

1. `DJANGO_PUBLIC_BASE_URL` must match the real Railway public URL or custom domain
2. `DATABASE_URL` must point to the Railway PostgreSQL service
3. If you use a custom domain, add it to:
   - `DJANGO_ALLOWED_HOSTS`
   - `DJANGO_CSRF_TRUSTED_ORIGINS`
4. `DJANGO_DEBUG` should be `False` in production

Examples:

```env
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,your-public-domain.up.railway.app,hr.yourdomain.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://your-public-domain.up.railway.app,https://hr.yourdomain.com
DJANGO_PUBLIC_BASE_URL=https://hr.yourdomain.com
```

## After First Deploy

Run or verify:

```bash
python manage.py collectstatic --no-input
python manage.py createsuperuser
```

## Scheduled Tasks

Railway scheduled jobs can be used for recurring compliance and expiry checks.

Recommended daily contract expiry job:

```bash
python manage.py check_contract_expiry
```

Suggested cadence:

- once per day in the early morning Kuwait time

What it does:

- checks active employee contracts with an `end_date` within the next 60 days
- creates in-app notifications for active HR-role users under the `contract` category
- sends notification emails through the existing notification delivery flow

## Important Storage Note

Railway containers are ephemeral by default.

For production use, attach persistent storage if you need to keep:

- uploaded employee and organization media
- backup ZIP files
- exported files saved on disk

Without a volume, code and database will work, but local filesystem uploads and generated files may not survive redeploys.
