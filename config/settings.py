import os
from sys import argv
from pathlib import Path
from urllib.parse import urlparse
from django.core.exceptions import ImproperlyConfigured

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file(BASE_DIR / ".env")

def _get_env_bool(name: str, default: bool = False) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}

railway_host = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
explicit_public_url = os.environ.get("DJANGO_PUBLIC_BASE_URL", "").strip()
argv_text = " ".join(argv).lower()
is_local_command = ("pytest" in argv_text or "py.test" in argv_text) or any(
    command in argv
    for command in {"runserver", "shell", "migrate", "makemigrations", "check", "test", "pytest", "py.test"}
)
is_test_run = "pytest" in argv_text or "py.test" in argv_text or " test" in f" {argv_text}"
DEBUG = _get_env_bool("DJANGO_DEBUG", default=not railway_host and not explicit_public_url and is_local_command)

SECRET_KEY = (
    os.environ.get("DJANGO_SECRET_KEY", "").strip()
    or os.environ.get("SECRET_KEY", "").strip()
)
if not SECRET_KEY:
    if DEBUG or (not railway_host and not explicit_public_url):
        SECRET_KEY = "django-insecure-local-development-key"
    else:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is disabled. "
            "Create a local .env from .env.example or set the environment variable explicitly."
        )

def _split_env_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _extract_host_from_url(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.hostname or "").strip()


def _normalize_origin(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return ""


allowed_hosts = set(_split_env_list(os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost")))
for derived_host in (railway_host, _extract_host_from_url(explicit_public_url)):
    if derived_host:
        allowed_hosts.add(derived_host)
ALLOWED_HOSTS = sorted(allowed_hosts)

csrf_trusted_origins = set(_split_env_list(os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "")))
for derived_origin in (
    f"https://{railway_host}" if railway_host else "",
    _normalize_origin(explicit_public_url),
):
    if derived_origin:
        csrf_trusted_origins.add(derived_origin)
CSRF_TRUSTED_ORIGINS = sorted(csrf_trusted_origins)


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Local apps
    "core",
    "accounts",
    "organization",
    "employees",
    "operations",
    "hr",
    "payroll",
    "notifications",
    "workcalendar",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "config.middleware.SessionTimeoutMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "config.context_processors.navbar_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


def _build_local_postgres_url() -> str | None:
    """Build a PostgreSQL URL from discrete env vars when DATABASE_URL isn't set."""
    name = os.environ.get("POSTGRES_DB", "nouraxis_local").strip()
    user = os.environ.get("POSTGRES_USER", "postgres").strip()
    password = os.environ.get("POSTGRES_PASSWORD", "postgres").strip()
    host = os.environ.get("POSTGRES_HOST", "127.0.0.1").strip()
    port = os.environ.get("POSTGRES_PORT", "").strip() or "5432"

    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


database_url = (
    os.environ.get("DATABASE_URL", "").strip()
    or os.environ.get("LOCAL_DATABASE_URL", "").strip()
    or _build_local_postgres_url()
)

if is_test_run and not os.environ.get("DJANGO_TEST_DATABASE_URL", "").strip():
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(BASE_DIR / "test_db.sqlite3"),
        }
    }
else:
    DATABASES = {
        "default": dj_database_url.config(
            default=os.environ.get("DJANGO_TEST_DATABASE_URL", "").strip() or database_url,
            conn_max_age=600,
        )
    }
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kuwait"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_URL = os.environ.get("DJANGO_MEDIA_URL", "/media/")
if os.environ.get("DJANGO_MEDIA_ROOT"):
    MEDIA_ROOT = Path(os.environ["DJANGO_MEDIA_ROOT"])
elif os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"):
    MEDIA_ROOT = Path(os.environ["RAILWAY_VOLUME_MOUNT_PATH"]) / "media"
else:
    MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

SESSION_INACTIVITY_TIMEOUT_SECONDS = int(
    os.environ.get("DJANGO_SESSION_INACTIVITY_TIMEOUT_SECONDS", "1800")
)
SESSION_TIMEOUT_WARNING_SECONDS = int(
    os.environ.get("DJANGO_SESSION_TIMEOUT_WARNING_SECONDS", "300")
)
SESSION_COOKIE_AGE = SESSION_INACTIVITY_TIMEOUT_SECONDS
SESSION_SAVE_EVERY_REQUEST = False

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    os.environ.get(
        "DJANGO_EMAIL_BACKEND",
        "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend",
    ),
).strip()
EMAIL_HOST = os.environ.get("EMAIL_HOST", os.environ.get("DJANGO_EMAIL_HOST", "localhost")).strip()
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", os.environ.get("DJANGO_EMAIL_PORT", "25")))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", os.environ.get("DJANGO_EMAIL_HOST_USER", "")).strip()
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", os.environ.get("DJANGO_EMAIL_HOST_PASSWORD", "")).strip()
EMAIL_USE_TLS = _get_env_bool("EMAIL_USE_TLS", default=_get_env_bool("DJANGO_EMAIL_USE_TLS", default=False))
EMAIL_USE_SSL = _get_env_bool("EMAIL_USE_SSL", default=_get_env_bool("DJANGO_EMAIL_USE_SSL", default=False))
EMAIL_TIMEOUT = int(os.environ.get("DJANGO_EMAIL_TIMEOUT", "10"))
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL",
    os.environ.get("DJANGO_DEFAULT_FROM_EMAIL", "NourAxis <no-reply@nouraxis.local>"),
).strip()
SERVER_EMAIL = os.environ.get("DJANGO_SERVER_EMAIL", DEFAULT_FROM_EMAIL).strip()

LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL", "INFO").strip().upper()
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
        "simple": {
            "format": "%(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose" if not DEBUG else "simple",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "core": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "employees": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "payroll": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },
        "django.utils.autoreload": {
            "handlers": ["console"],
            "level": os.environ.get("DJANGO_AUTORELOAD_LOG_LEVEL", "WARNING").strip().upper(),
            "propagate": False,
        },
    },
}

if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# ============================================================
# Backup Center settings
# ============================================================
# Change this folder if you want backups saved somewhere else.
# Example on Windows:
# HR_BACKUP_ROOT = Path(r"C:/Users/AbuNour/Desktop/HR_System_Backups")
if os.environ.get("HR_BACKUP_ROOT"):
    HR_BACKUP_ROOT = Path(os.environ["HR_BACKUP_ROOT"])
elif os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"):
    HR_BACKUP_ROOT = Path(os.environ["RAILWAY_VOLUME_MOUNT_PATH"]) / "backups"
else:
    HR_BACKUP_ROOT = Path.home() / "Desktop" / "NourAxis_Backups"

# Only these project items will be included in the generated zip.
HR_BACKUP_INCLUDE_PATHS = [
    "manage.py",
    "build.sh",
    "Procfile",
    "gunicorn.conf.py",
    ".env.example",
    ".gitignore",
    "POSTGRES_MIGRATION.md",
    "RAILWAY_DEPLOY.md",
    "requirements.txt",
    "pytest.ini",
    "nixpacks.toml",
    "media",
    "employees",
    "notifications",
    "operations",
    "organization",
    "accounts",
    "core",
    "hr",
    "payroll",
    "workcalendar",
    "templates",
    "static",
    "config",
    "requirements.txt",
]

if (BASE_DIR / "db.sqlite3").exists():
    HR_BACKUP_INCLUDE_PATHS.insert(1, "db.sqlite3")

# Prevent recursive/self backups and avoid noisy folders.
HR_BACKUP_EXCLUDE_DIR_NAMES = {
    ".git",
    ".idea",
    ".vscode",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "env",
    "site-packages",
    "staticfiles",
    "NourAxis_Backups",
    "system_backups",
}

HR_BACKUP_EXCLUDE_FILE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".sqlite3-shm",
    ".sqlite3-wal",
    ".log",
    ".tmp",
}

HR_BACKUP_MAX_LISTED_FILES = 12


def _detect_pg_dump_command() -> str:
    explicit = os.environ.get("HR_BACKUP_PG_DUMP_COMMAND", "").strip()
    if explicit:
        return explicit

    common_windows_candidates = [
        r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe",
        r"C:\Program Files\PostgreSQL\17\bin\pg_dump.exe",
        r"C:\Program Files\PostgreSQL\16\bin\pg_dump.exe",
        r"C:\Program Files\PostgreSQL\15\bin\pg_dump.exe",
        r"C:\Program Files\PostgreSQL\14\bin\pg_dump.exe",
        r"C:\Program Files\PostgreSQL\13\bin\pg_dump.exe",
    ]
    for candidate in common_windows_candidates:
        if Path(candidate).exists():
            return candidate

    return "pg_dump"


HR_BACKUP_PG_DUMP_COMMAND = _detect_pg_dump_command()
