#!/bin/bash

# SSL 인증서 갱신 스크립트
# crontab에 등록하여 자동 갱신 가능

echo "### SSL 인증서 갱신 시도 중..."

docker-compose run --rm certbot renew

echo "### Nginx 설정 재로드 중..."
docker-compose exec nginx nginx -s reload

echo "### 인증서 갱신 완료"
