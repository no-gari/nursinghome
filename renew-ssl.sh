#!/bin/bash
set -euo pipefail

# SSL 인증서 갱신 스크립트
# crontab에 등록하여 자동 갱신 가능

# Docker Compose 명령 감지
if command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
elif docker compose version >/dev/null 2>&1; then
  DC="docker compose"
else
  echo 'Error: docker-compose (or docker compose) is not installed.' >&2
  exit 1
fi

echo "### SSL 인증서 갱신 시도 중..."
$DC run --rm certbot renew

echo "### Nginx 설정 문법 검사 중..."
$DC exec nginx nginx -t

echo "### Nginx 설정 재로드 중..."
$DC exec nginx nginx -s reload

echo "### 인증서 갱신 완료"
