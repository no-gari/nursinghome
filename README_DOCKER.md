# Nursinghome Server Docker 배포

## 구성
- app: Django + Channels (daphne)
- redis: channels layer/pub-sub
- nginx: 정적/미디어 서빙 + 리버스프록시 + WebSocket 지원

## 빠른 시작
```bash
docker compose build
docker compose up -d
```

첫 실행 후 브라우저에서 `http://localhost` 접속.

## 환경변수
`.env.example` 참고하여 `.env` 생성. 주요 항목:
- DJANGO_SECRET: 프로덕션에서 강력한 랜덤 문자열로 변경
- DJANGO_DEBUG: False (프로덕션)
- DJANGO_ALLOWED_HOSTS: 쉼표 구분 도메인 목록
- DJANGO_CORS_ALLOWED_ORIGINS: CORS 허용 프론트엔드 URL
- REDIS_HOST/PORT: 기본 redis
- SUPERUSER (선택): 초기 관리자 자동 생성

## 정적/미디어
- collectstatic 결과: named volume `static_volume`
- 업로드 미디어: `media_volume`

## 로그 확인
```bash
docker compose logs -f app
docker compose logs -f nginx
```

## 재배포 (코드 변경)
소스 수정 후:
```bash
docker compose restart app
```
(의존 패키지 변경시 build 필요)

## 마이그레이션 수동 실행
```bash
docker compose exec app python manage.py migrate
```

## 쉘 접속
```bash
docker compose exec app python manage.py shell
```

## WebSocket
- `/ws/` prefix 는 nginx 설정에서 업그레이드 처리됨.

## 프로덕션 권장 추가
- HTTPS(TLS): nginx + certbot 컨테이너 추가 또는 외부 LB 사용
- DB: SQLite 대신 PostgreSQL (compose service 추가)
- 보안: SECRET, API 키는 Vault/Secret Manager 사용


