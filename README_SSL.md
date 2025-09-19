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

## SSL 인증서 발급 및 설정

### 1단계: 설정 파일 수정

1. **docker-compose.yml에서 도메인 설정**:
   - `your-domain.com`을 실제 도메인으로 변경
   - `your-email@example.com`을 실제 이메일로 변경

2. **nginx/default.conf에서 도메인 설정**:
   - 모든 `your-domain.com`을 실제 도메인으로 변경

### 2단계: 초기 인증서 발급

```bash
# 스테이징 환경에서 테스트 (권장)
./init-letsencrypt.sh your-domain.com your-email@example.com

# 테스트가 성공하면 프로덕션 인증서 발급
# init-letsencrypt.sh에서 staging=0으로 변경 후 재실행
./init-letsencrypt.sh your-domain.com your-email@example.com
```

### 3단계: 서비스 시작

```bash
# 모든 서비스 시작
docker-compose up -d

# 로그 확인
docker-compose logs nginx
docker-compose logs certbot
```

## 인증서 자동 갱신 설정

Let's Encrypt 인증서는 90일마다 갱신해야 합니다. 자동 갱신을 위해 crontab을 설정하세요:

```bash
# crontab 편집
crontab -e

# 다음 라인 추가 (매일 오전 3시에 갱신 확인)
0 3 * * * /path/to/your/project/renew-ssl.sh >> /var/log/letsencrypt-renew.log 2>&1
```

## 수동 인증서 갱신

```bash
# 수동으로 인증서 갱신
./renew-ssl.sh
```

## 문제 해결

### 1. 인증서 발급 실패
- DNS 설정이 올바른지 확인
- 도메인이 서버를 가리키는지 확인
- 방화벽에서 포트 80, 443이 열려있는지 확인

### 2. Nginx 시작 실패
```bash
# Nginx 로그 확인
docker-compose logs nginx

# 설정 파일 문법 검사
docker-compose exec nginx nginx -t
```

### 3. 스테이징에서 프로덕션으로 전환
1. `init-letsencrypt.sh`에서 `staging=0`으로 변경
2. 기존 인증서 삭제: `sudo rm -rf ./certbot/conf/live/your-domain.com`
3. 스크립트 재실행

## 보안 권장사항

현재 nginx 설정에 포함된 보안 기능들:
- TLS 1.2, 1.3만 허용
- 강력한 암호화 스위트 사용
- HSTS 헤더 적용
- 보안 헤더 추가 (X-Frame-Options, X-Content-Type-Options 등)

## 인증서 상태 확인

```bash
# 인증서 만료일 확인
docker-compose run --rm certbot certificates

# SSL 설정 테스트
# https://www.ssllabs.com/ssltest/ 에서 도메인 테스트
```
