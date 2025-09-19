#!/bin/bash

# Let's Encrypt 초기 설정 스크립트
# 사용법: ./init-letsencrypt.sh your-domain.com your-email@example.com

if ! [ -x "$(command -v docker-compose)" ]; then
  echo 'Error: docker-compose is not installed.' >&2
  exit 1
fi

domains=($1)
email="$2" # 실제 이메일 주소로 변경하세요
data_path="./certbot"
staging=1 # 테스트용. 실제 운영시 0으로 변경

if [ -d "$data_path" ]; then
  read -p "기존 데이터가 발견되었습니다. $data_path 폴더를 삭제하고 새로 시작하시겠습니까? (y/N) " decision
  if [ "$decision" != "Y" ] && [ "$decision" != "y" ]; then
    exit
  fi
fi

if [ "$staging" != "0" ]; then
  echo "### 스테이징 모드로 실행합니다 (테스트용)"
fi

echo "### Nginx와 Certbot 다운로드 중..."
docker-compose down
docker-compose pull nginx certbot

echo "### 임시 인증서 생성 중..."
path="/etc/letsencrypt/live/$domains"
mkdir -p "$data_path/conf/live/$domains"
docker-compose run --rm --entrypoint "\
  openssl req -x509 -nodes -newkey rsa:1024 -days 1\
    -keyout '$path/privkey.pem' \
    -out '$path/fullchain.pem' \
    -subj '/CN=localhost'" certbot
echo

echo "### Nginx 시작 중..."
docker-compose up --force-recreate -d nginx
echo

echo "### 임시 인증서 삭제 중..."
docker-compose run --rm --entrypoint "\
  rm -Rf /etc/letsencrypt/live/$domains && \
  rm -Rf /etc/letsencrypt/archive/$domains && \
  rm -Rf /etc/letsencrypt/renewal/$domains.conf" certbot
echo

echo "### Let's Encrypt 인증서 요청 중..."

# 이메일 인자 선택
case "$email" in
  "") email_arg="--register-unsafely-without-email" ;;
  *) email_arg="--email $email" ;;
esac

# 스테이징 플래그 설정
if [ $staging != "0" ]; then staging_arg="--staging"; fi

docker-compose run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot \
    $staging_arg \
    $email_arg \
    -d $domains \
    --rsa-key-size 2048 \
    --agree-tos \
    --force-renewal" certbot
echo

echo "### Nginx 재시작 중..."
docker-compose exec nginx nginx -s reload
