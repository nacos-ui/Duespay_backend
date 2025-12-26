import os

import cloudinary
import dj_database_url
from decouple import config

from .base import *

DEBUG = False


INSTALLED_APPS += ["cloudinary", "cloudinary_storage"]

CORS_ALLOWED_ORIGINS = [
    "https://duespay.vercel.app",
    "https://duespay.app",
    "https://www.duespay.app",
    "http://localhost:5173",
    "http://localhost:8000"
]

CSRF_TRUSTED_ORIGINS = [
    "https://duespay-backend.fly.dev",
    "http://localhost:8000",
    "https://duespay.onrender.com",
    "https://duespay.pythonanywhere.com",
    "https://duespay-5hrhv.sevalla.app",
    "https://duespay-backend-production.up.railway.app",
    "https://duespay-backend.onrender.com",
]

CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https:\/\/([a-zA-Z0-9-]+)\.duespay.app$",
]

DATABASES = {
    "default": dj_database_url.config(
        default=config("DATABASE_URL"), conn_max_age=600, ssl_require=True
    )
}

MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
    "whitenoise.middleware.WhiteNoiseMiddleware",
)
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"


ALLOWED_HOSTS = [
    "duespay.pythonanywhere.com",
    "duespay-backend.onrender.com",
    "duespay.onrender.com",
    "duespay-backend.fly.dev",
    "duespay-backend-production.up.railway.app",
    "duespay-5hrhv.sevalla.app",
    "localhost"
]


CLOUDINARY_STORAGE = {
    "CLOUD_NAME": config("CLOUDINARY_CLOUD_NAME"),
    "API_KEY": config("CLOUDINARY_API_KEY"),
    "API_SECRET": config("CLOUDINARY_API_SECRET"),
}


cloudinary.config(
    cloud_name=CLOUDINARY_STORAGE["CLOUD_NAME"],
    api_key=CLOUDINARY_STORAGE["API_KEY"],
    api_secret=CLOUDINARY_STORAGE["API_SECRET"],
)

EMAIL_BACKEND = "anymail.backends.brevo.EmailBackend"

ANYMAIL = {
    "BREVO_API_KEY": config("BREVO_API_KEY"),
}

DEFAULT_FROM_EMAIL = "DuesPay <jcmailer.1@gmail.com>"

KORAPAY_SECRET_KEY = config("KORAPAY_SECRET_KEY", default="")
KORAPAY_PUBLIC_KEY = config("KORAPAY_PUBLIC_KEY", default="")
KORAPAY_ENCRYPTION_KEY = config("KORAPAY_ENCRYPTION_KEY", default="")

PAYSTACK_SECRET = config('PAYSTACK_SECRET', default="")
PAYSTACK_PUBLIC = config('PAYSTACK_PUBLIC', default="")
PAYSTACK_WEBHOOK_SECRET = config('PAYSTACK_WEBHOOK_SECRET', default="")
PAYSTACK_WEBHOOK_URL = config('PAYSTACK_WEBHOOK_URL', default="https://f43d38558991.ngrok-free.app/api/transactions/webhook/")

DEFAULT_FILE_STORAGE = "cloudinary_storage.storage.MediaCloudinaryStorage"

FRONTEND_URL = "https://nacos-duespay.vercel.app"
BACKEND_URL = "https://duespay-backend.onrender.com"
KORAPAY_WEBHOOK_URL = f"{BACKEND_URL}/api/transactions/webhook/"