#!/bin/sh
set -e

# 실행 환경 표시
echo "[entrypoint] Starting Django (migrate + collectstatic + daphne)"

python manage.py migrate --noinput
python manage.py collectstatic --noinput

# 필요 시 초기 superuser 자동 생성 (옵션)
if [ "$DJANGO_SUPERUSER_USERNAME" ] && [ "$DJANGO_SUPERUSER_PASSWORD" ]; then
  echo "[entrypoint] Creating superuser if not exists"
  python manage.py shell <<EOF
from django.contrib.auth import get_user_model
User = get_user_model()
username = "${DJANGO_SUPERUSER_USERNAME}"
if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username=username, email="${DJANGO_SUPERUSER_EMAIL}", password="${DJANGO_SUPERUSER_PASSWORD}")
    print("Superuser created")
else:
    print("Superuser already exists")
EOF
fi

# Daphne (ASGI) 실행
exec daphne -b 0.0.0.0 -p 8000 config.asgi:application

