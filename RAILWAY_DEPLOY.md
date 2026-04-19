# Railway Deployment Guide

This project is prepared to run on Railway as the active deployment platform.

## What Was Prepared

- Platform-neutral Gunicorn startup through `gunicorn.conf.py`
- `Procfile` for Railway web process detection
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

## Important Storage Note

Railway containers are ephemeral by default.

For production use, attach persistent storage if you need to keep:

- uploaded employee and organization media
- backup ZIP files
- exported files saved on disk

Without a volume, code and database will work, but local filesystem uploads and generated files may not survive redeploys.
