import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# 환경변수 로드 (.env는 docker-compose env_file 로 주입)
from dotenv import load_dotenv
load_dotenv()

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv("DJANGO_SECRET", "")

# DEBUG / ALLOWED_HOSTS 환경변수화
DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() == "true"
ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]

KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "")
KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET", "")
KAKAO_REDIRECT_URI = os.getenv("KAKAO_REDIRECT_URI", "")

# Google Geocoding API 키
GOOGLE_GEOCODING_API_KEY = os.getenv("GOOGLE_GEOCODING_API_KEY", "")
# Google Maps JavaScript API 키 (웹에서 지도 표시용)
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_GEOCODING_API_KEY", "")

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'daphne',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'core',
    'storages',
    'account',
    'ckeditor',
    'blog',
    'channels',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

USE_SQLITE = False

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'ko-kr'
TIME_ZONE = 'Asia/Seoul'
USE_I18N = True
USE_TZ = True

STATIC_ROOT = os.path.join(BASE_DIR, 'static/')
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media/')

# BASE STATIC, MEDIA ROOT
AWS_S3_SECURE_URLS = True
AWS_REGION = 'ap-northeast-2'
AWS_STORAGE_BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')
AWS_QUERYSTRING_AUTH = False
AWS_S3_HOST = '%s.s3.ap-northeast-2.amazonaws.com' % AWS_STORAGE_BUCKET_NAME
AWS_ACCESS_KEY_ID = os.getenv('S3_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('S3_SECRET_ACCESS_KEY')
AWS_DEFAULT_ACL = None
AWS_S3_OBJECT_PARAMETERS = {
    'CacheControl': 'max-age=86400',
}

STATICFILES_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
MEDIAFILES_LOCATION = 'media'
STATIC_URL = f'https://{AWS_S3_HOST}/'

CKEDITOR_CONFIGS = {
    'default': {
        'toolbar': 'full',
        'height': 400,
        'width': '100%',
        'extraPlugins': ','.join(['codesnippet']),
        'codeSnippet_theme': 'prism',
        'removePlugins': 'stylesheetparser',
        'forcePasteAsPlainText': False,
    }
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'DEFAULT_PARSER_CLASSES': ['rest_framework.parsers.JSONParser'],
}

_raw_cors = os.getenv("DJANGO_CORS_ALLOWED_ORIGINS")

if _raw_cors:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in _raw_cors.split(',') if o.strip()]

CORS_ALLOW_CREDENTIALS = True

# RAG 시스템 설정
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")
NAVER_API_TIMEOUT = 5

# Redis / Channels 설정 (환경변수화)
REDIS_HOST = os.getenv('REDIS_HOST', '127.0.0.1')
REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
CHANNEL_LAYERS = {
  'default': {
    'BACKEND': 'channels_redis.core.RedisChannelLayer',
    'CONFIG': {'hosts': [(REDIS_HOST, REDIS_PORT)]},
  }
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {'class': 'logging.StreamHandler'},
    },
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {
        'core.consumers': {'handlers': ['console'], 'level': 'DEBUG', 'propagate': False},
    },
}

OPENAI_PROMPT_ID = os.environ.get("OPENAI_PROMPT_ID", "")

# 배포 환경에서 필수 체크
if not DEBUG and not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET 환경변수가 설정되지 않았습니다 (production mode).")