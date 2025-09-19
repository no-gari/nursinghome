#!/bin/bash

set -euo pipefail

# Let's Encrypt 초기 설정 스크립트
# 사용법:
#   ./init-letsencrypt.sh example.com,email@example.com  # 쉼표로 여러 도메인 가능 (예: example.com,www.example.com)
#   또는
#   ./init-letsencrypt.sh "example.com,www.example.com" email@example.com

# Docker Compose 명령 감지 (v1: docker-compose, v2: docker compose)
if command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
elif docker compose version >/dev/null 2>&1; then
  DC="docker compose"
else
  echo 'Error: docker-compose (or docker compose) is not installed.' >&2
  exit 1
fi

# 인자 파싱
if [ "${1:-}" = "" ] || [ "${2:-}" = "" ]; then
  echo "Usage: $0 <domain[,alt1,alt2,...]> <email>" >&2
  exit 1
fi

raw_domains="$1"
email="$2"

# 쉼표로 구분된 도메인 리스트 파싱
IFS=',' read -r -a domains <<< "$raw_domains"
PRIMARY_DOMAIN="${domains[0]}"

data_path="./certbot"
# 스테이징 모드: 1(테스트), 0(운영). 환경변수 LE_STAGING 로도 제어 가능
staging="${LE_STAGING:-1}"

if [ -d "$data_path" ]; then
  read -p "기존 데이터가 발견되었습니다. $data_path 폴더를 삭제하고 새로 시작하시겠습니까? (y/N) " decision
  if [ "$decision" != "Y" ] && [ "$decision" != "y" ]; then
    echo "중단합니다."
    exit 0
  fi
fi

if [ "$staging" != "0" ]; then
  echo "### 스테이징 모드로 실행합니다 (테스트용)"
fi

echo "### Nginx와 Certbot 이미지 동기화 중..."
$DC down || true
$DC pull nginx certbot

echo "### 임시 인증서 생성 중..."
path="/etc/letsencrypt/live/$PRIMARY_DOMAIN"
mkdir -p "$data_path/conf/live/$PRIMARY_DOMAIN"
$DC run --rm --entrypoint "\
  openssl req -x509 -nodes -newkey rsa:1024 -days 1\
    -keyout '$path/privkey.pem' \
    -out '$path/fullchain.pem' \
    -subj '/CN=localhost'" certbot

echo "### Nginx 시작 중..."
$DC up --force-recreate -d nginx

echo "### 임시 인증서 정리 중..."
$DC run --rm --entrypoint "\
  rm -Rf /etc/letsencrypt/live/$PRIMARY_DOMAIN && \
  rm -Rf /etc/letsencrypt/archive/$PRIMARY_DOMAIN && \
  rm -Rf /etc/letsencrypt/renewal/$PRIMARY_DOMAIN.conf" certbot

echo "### Let's Encrypt 인증서 요청 중..."

# 이메일 인자 선택
case "$email" in
  "") email_arg="--register-unsafely-without-email" ;;
  *)  email_arg="--email $email" ;;
esac

# 스테이징 플래그 설정
staging_arg=""
if [ "$staging" != "0" ]; then staging_arg="--staging"; fi

# -d 파라미터 구성
domain_args=()
for d in "${domains[@]}"; do
  domain_args+=( -d "$d" )
done

$DC run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    $staging_arg \
    $email_arg \
    ${domain_args[@]} \
    --rsa-key-size 2048 \
    --agree-tos \
    --force-renewal" certbot

echo "### Nginx 재시작 중..."
$DC exec nginx nginx -s reload

echo "### 완료: 인증서가 발급되었습니다. (도메인: ${domains[*]})"
