# Python 기반 Django + Channels (daphne) 컨테이너
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# 시스템 패키지 (빌드 및 일부 파이썬 패키지 의존성)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev libssl-dev \
    libxml2-dev libxslt1-dev \
    curl git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저 복사 (캐시 활용)
COPY requirements.txt ./
RUN pip install -r requirements.txt

# 프로젝트 소스
COPY . .

# 실행 스크립트 실행권한
RUN chmod +x scripts/entrypoint.sh

EXPOSE 8000

# 기본 실행 (docker-compose 에서 override 가능)
CMD ["/app/scripts/entrypoint.sh"]

