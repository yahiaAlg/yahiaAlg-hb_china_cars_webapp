"""
Django settings for car_trading project.
"""

import os
import dotenv
from pathlib import Path

dotenv.load_dotenv()


BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# SECURITY
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure-your-secret-key-here-change-in-production",
)

DEBUG = os.environ.get("DEBUG", "True") == "True"

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")

# ---------------------------------------------------------------------------
# APPLICATION DEFINITION
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Third party apps
    "crispy_forms",
    "crispy_bootstrap4",
    "import_export",
    # Local apps
    "core",
    "suppliers",
    "purchases",
    "inventory",
    "customers",
    "sales",
    "payments",
    "commissions",
    "reports",
    "system_settings",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # ↓ WhiteNoise must come right after SecurityMiddleware
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "car_trading.middleware.CurrentUserMiddleware",  # custom middleware to track current user in signals
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "car_trading.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.global_settings",
            ],
        },
    },
]

WSGI_APPLICATION = "car_trading.wsgi.application"

# ---------------------------------------------------------------------------
# DATABASE  —  SQLite
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}
# for mysql, use with a db named bureau_db and a user named root with no password (for development only):

# DATABASES = {
#    "default": {
#        "ENGINE": "django.db.backends.mysql",
#        "NAME": os.environ.get("DB_NAME", "bureau_db"),
#        "USER": os.environ.get("DB_USER", "root"),
#        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
#        "HOST": os.environ.get("DB_HOST", "localhost"),
#        "PORT": os.environ.get("DB_PORT", "3306"),
#    }
# }
# ---------------------------------------------------------------------------
# PASSWORD VALIDATION
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# INTERNATIONALISATION
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "fr-dz"
TIME_ZONE = "Africa/Algiers"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# STATIC FILES  —  WhiteNoise
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Compress and fingerprint static files for production
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ---------------------------------------------------------------------------
# MEDIA FILES
# ---------------------------------------------------------------------------
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---------------------------------------------------------------------------
# MISC
# ---------------------------------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap4"
CRISPY_TEMPLATE_PACK = "bootstrap4"

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

# ---------------------------------------------------------------------------
# COMPANY INFO
# ---------------------------------------------------------------------------
COMPANY_NAME = "Bureau de Commerce Automobile Algérien"
COMPANY_NIF = "123456789012345"
COMPANY_ADDRESS = "Alger, Algérie"
COMPANY_PHONE = "+213 21 XX XX XX"
COMPANY_EMAIL = "info@bureauauto.dz"

DEFAULT_TVA_RATE = 19.0
DEFAULT_TARIFF_RATE = 25.0
DEFAULT_COMMISSION_RATE = 10.0

SUPPORTED_CURRENCIES = ["USD", "CNY", "DA"]
DEFAULT_CURRENCY = "DA"

USE_THOUSAND_SEPARATOR = True
THOUSAND_SEPARATOR = ","
DECIMAL_SEPARATOR = "."
NUMBER_GROUPING = 3
