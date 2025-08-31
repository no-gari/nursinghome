import time
import requests
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db.models import Q
from core.models import Hospital


class Command(BaseCommand):
    help = 'Hospital 모델의 주소(location)를 Google Geocoding API로 좌표(latitude, longitude)로 변환합니다.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=None, help='처리할 Hospital 최대 개수')
        parser.add_argument('--force', action='store_true', help='기존 좌표가 있어도 다시 조회')
        parser.add_argument('--delay', type=float, default=0.1, help='API 호출 간 지연 (초)')
        parser.add_argument('--api-key', type=str, default=None, help='직접 API Key 지정 (미지정 시 settings.GOOGLE_GEOCODING_API_KEY 사용)')

    def handle(self, *args, **options):
        api_key = options['api_key'] or getattr(settings, 'GOOGLE_MAPS_API_KEY', None)
        if not api_key:
            raise CommandError('Google Geocoding API Key가 설정되어 있지 않습니다 (옵션 --api-key 또는 settings.GOOGLE_GEOCODING_API_KEY).')

        limit = options['limit']
        force = options['force']
        delay = options['delay']

        # 대상 queryset 구성
        if force:
            qs = Hospital.objects.exclude(location='')  # 주소가 비어있지 않은 모든 대상
        else:
            qs = (Hospital.objects.filter(location__isnull=False)
                  .exclude(location='')
                  .filter(Q(latitude__isnull=True) | Q(longitude__isnull=True)))

        if limit:
            qs = qs.order_by('id')[:limit]

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.WARNING('처리할 Hospital 레코드가 없습니다.'))
            return

        self.stdout.write(self.style.SUCCESS(f'Hospital 좌표 변환 시작 (총 {total}건)'))

        success = 0
        failure = 0

        for idx, hospital in enumerate(qs, 1):
            addr = (hospital.location or '').strip()
            self.stdout.write(f'[{idx}/{total}] {hospital.name} - 주소: {addr[:80]}')
            if not addr:
                failure += 1
                self.stdout.write(self.style.WARNING('  ✗ 주소 없음 - 건너뜀'))
                continue

            try:
                lat, lng = self._geocode(api_key, addr)
                if lat is None or lng is None:
                    failure += 1
                    self.stdout.write(self.style.WARNING('  ✗ 좌표 조회 실패'))
                else:
                    hospital.latitude = Decimal(str(lat))
                    hospital.longitude = Decimal(str(lng))
                    hospital.save(update_fields=['latitude', 'longitude'])
                    success += 1
                    self.stdout.write(self.style.SUCCESS(f'  ✓ {lat}, {lng} 저장'))
            except Exception as e:  # noqa: BLE001 (단순 관리커맨드이므로 포괄 처리)
                failure += 1
                self.stdout.write(self.style.ERROR(f'  ✗ 예외 발생: {e}'))

            if delay > 0:
                time.sleep(delay)

        self.stdout.write(self.style.SUCCESS(f'완료: 성공 {success}건 / 실패 {failure}건'))

    def _geocode(self, api_key: str, address: str):
        """Google Geocoding API 호출하여 (lat, lng) 반환. 실패 시 (None, None)."""
        url = 'https://maps.googleapis.com/maps/api/geocode/json'
        params = {
            'address': address,
            'key': api_key,
            'region': 'kr',
            'language': 'ko',
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            status = data.get('status')
            if status == 'OK' and data.get('results'):
                loc = data['results'][0]['geometry']['location']
                return float(loc['lat']), float(loc['lng'])
            if status == 'OVER_QUERY_LIMIT':
                self.stdout.write(self.style.ERROR('  API 쿼터 초과 (OVER_QUERY_LIMIT) - 지연/키 확인 필요'))
            elif status == 'ZERO_RESULTS':
                self.stdout.write(self.style.WARNING('  결과 없음 (ZERO_RESULTS)'))
            else:
                self.stdout.write(self.style.WARNING(f'  상태 비정상: {status}'))
        except requests.exceptions.RequestException as e:  # 네트워크/HTTP 오류
            self.stdout.write(self.style.ERROR(f'  요청 실패: {e}'))
        except (KeyError, ValueError, TypeError) as e:  # 파싱 오류
            self.stdout.write(self.style.ERROR(f'  응답 파싱 오류: {e}'))
        return None, None
