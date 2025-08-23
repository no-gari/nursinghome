from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Hospital


class Command(BaseCommand):
    help = 'Hospital 모델의 location 정보를 분석하여 sido와 sigungu 필드를 설정합니다'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='실제 업데이트하지 않고 결과만 출력'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        hospitals = Hospital.objects.all()
        updated_count = 0
        failed_count = 0
        error_count = 0
        failed_locations = []
        error_hospitals = []

        self.stdout.write(f'총 {hospitals.count()}개 병원의 지역 정보를 분석합니다...')

        for hospital in hospitals:
            if not hospital.location:
                failed_count += 1
                failed_locations.append(f"{hospital.name} (코드: {hospital.code}) - 위치 정보 없음")
                continue

            location = hospital.location.strip()
            sido, sigungu = self.parse_location(location)

            if sido:
                try:
                    if not dry_run:
                        with transaction.atomic():
                            hospital.sido = sido
                            hospital.sigungu = sigungu or ''
                            hospital.save(update_fields=['sido', 'sigungu'])

                    updated_count += 1
                    self.stdout.write(f'✓ {hospital.name}: {sido} {sigungu or "(시군구 없음)"}')

                except Exception as e:
                    error_count += 1
                    error_message = f'❌ {hospital.name}: {sido} {sigungu or "(시군구 없음)"} - ERROR: {str(e)}'
                    self.stdout.write(self.style.ERROR(error_message))
                    error_hospitals.append(f"{hospital.name} (코드: {hospital.code}) - {location} - {str(e)}")
            else:
                failed_count += 1
                failed_locations.append(f"{hospital.name} (코드: {hospital.code}) - {location}")

        # 결과 출력
        self.stdout.write(self.style.SUCCESS(f'\n완료: {updated_count}개 병원 업데이트'))
        self.stdout.write(self.style.WARNING(f'실패: {failed_count}개 병원'))
        if error_count > 0:
            self.stdout.write(self.style.ERROR(f'에러: {error_count}개 병원'))

        if failed_locations:
            self.stdout.write(self.style.ERROR('\n분석 실패한 병원들:'))
            for location in failed_locations[:20]:  # 최대 20개만 출력
                self.stdout.write(f'  - {location}')
            if len(failed_locations) > 20:
                self.stdout.write(f'  ... 외 {len(failed_locations) - 20}개')

        if error_hospitals:
            self.stdout.write(self.style.ERROR('\n데이터베이스 에러 발생한 병원들:'))
            for error in error_hospitals[:20]:  # 최대 20개만 출력
                self.stdout.write(f'  - {error}')
            if len(error_hospitals) > 20:
                self.stdout.write(f'  ... 외 {len(error_hospitals) - 20}개')

    def parse_location(self, location):
        """주소를 스페이스로 분리하여 시도와 시군구를 추출"""
        if not location:
            return None, None

        # 스페이스로 분리
        parts = location.split()

        if len(parts) < 1:
            return None, None

        # 첫 번째 부분이 시도
        sido = parts[0] if len(parts) > 0 else None

        # 두 번째 부분이 시군구 (있는 경우)
        sigungu = parts[1] if len(parts) > 1 else None

        return sido, sigungu
