# SSL/HTTPS 설정 가이드

이 프로젝트에서 Let's Encrypt를 사용하여 SSL 인증서를 발급받고 HTTPS를 적용하는 방법입니다.

## 사전 준비사항

1. **도메인이 서버 IP를 가리키도록 DNS 설정**
   - A 레코드: your-domain.com → 서버 IP
   - A 레코드: www.your-domain.com → 서버 IP

2. **방화벽 설정**
   ```bash
   # 포트 80, 443 열기 (Ubuntu/CentOS)
   sudo ufw allow 80
   sudo ufw allow 443
   ```

3. **파일 권한**
   ```bash
   chmod +x init-letsencrypt.sh renew-ssl.sh
   ```

## SSL 인증서 발급 및 설정

### 1단계: 설정 파일 수정

1. **nginx/default.conf에서 도메인/경로 확인**:
   - `server_name`을 실제 도메인으로 변경 (예: `anonnursing.com www.anonnursing.com`)
   - 인증서 경로가 첫 번째 도메인 기준으로 맞는지 확인
     - 예: 첫 번째 도메인이 `anonnursing.com`이면
       - `ssl_certificate /etc/letsencrypt/live/anonnursing.com/fullchain.pem;`
       - `ssl_certificate_key /etc/letsencrypt/live/anonnursing.com/privkey.pem;`

2. (선택) **docker-compose.yml 이메일/도메인 설정은 필요 없음**:
   - certbot 서비스는 기본적으로 대기만 하며, 발급은 스크립트로 수행합니다.

### 2단계: 초기 인증서 발급

도메인은 쉼표로 여러 개를 지정할 수 있습니다. 첫 번째 도메인이 인증서 저장 경로의 기준이 됩니다.

```bash
# 스테이징(테스트) 환경에서 발급 시도 (권장)
LE_STAGING=1 ./init-letsencrypt.sh "your-domain.com,www.your-domain.com" your-email@example.com

# 테스트가 성공하면 프로덕션 인증서 발급
LE_STAGING=0 ./init-letsencrypt.sh "your-domain.com,www.your-domain.com" your-email@example.com
```

- 위 스크립트는 자동으로 Nginx를 올리고(80 포트 제공), ACME 검증 후 인증서를 발급합니다.

### 3단계: 서비스 시작/재시작

```bash
# 모든 서비스 시작
# Docker Compose v1: docker-compose, v2: docker compose
docker compose up -d  # 또는 docker-compose up -d

# 로그 확인
docker compose logs nginx | tail -n 100
```

## 인증서 자동 갱신 설정

Let's Encrypt 인증서는 90일마다 갱신해야 합니다. 자동 갱신을 위해 crontab을 설정하세요:

```bash
# crontab 편집
crontab -e

# 다음 라인 추가 (매일 오전 3시에 갱신 확인)
0 3 * * * cd /path/to/your/project && ./renew-ssl.sh >> /var/log/letsencrypt-renew.log 2>&1
```

## 수동 인증서 갱신

```bash
# 수동으로 인증서 갱신
./renew-ssl.sh
```

## 문제 해결

### 1. 인증서 발급 실패
- DNS 설정이 올바른지 확인 (루트/WWW 모두 서버 공인 IP로)
- 방화벽에서 포트 80, 443이 열려있는지 확인
- `server_name`이 요청 도메인과 일치하는지 확인
- ACME 경로가 열려있는지 확인:
  ```bash
  # 임시 파일을 만들어 HTTP로 접근 확인
  echo test > certbot/www/.well-known/acme-challenge/health
  curl -I http://your-domain.com/.well-known/acme-challenge/health
  ```
  - 200이 나오면 OK, 301/302 리다이렉트 없이 바로 응답이어야 합니다.
- Nginx 에러 로그 확인:
  ```bash
  docker compose logs nginx | tail -n 200
  ```

### 2. Nginx 시작 실패
```bash
# 설정 파일 문법 검사
docker compose exec nginx nginx -t
```

### 3. 스테이징에서 프로덕션으로 전환
1. 스크립트 실행 시 `LE_STAGING=0` 설정
2. (문제 발생 시) 기존 인증서 삭제: `sudo rm -rf ./certbot/conf/live/your-domain.com ./certbot/conf/archive/your-domain.com ./certbot/conf/renewal/your-domain.com.conf`
3. 스크립트 재실행

## 보안 권장사항

현재 nginx 설정에 포함된 보안 기능들:
- TLS 1.2, 1.3만 허용
- 강력한 암호화 스위트 사용
- HSTS 헤더 적용
- 보안 헤더 추가 (X-Frame-Options, X-Content-Type-Options 등)

## 인증서 상태 확인

```bash
# 인증서 목록/만료일 확인
docker compose run --rm certbot certificates

# SSL 설정 테스트
# https://www.ssllabs.com/ssltest/ 에서 도메인 테스트
```
