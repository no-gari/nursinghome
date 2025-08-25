import requests
import time
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Hospital, Tag
from tqdm import tqdm


class Command(BaseCommand):
    help = 'Hospital의 code를 사용하여 eroum 사이트에서 태그 정보를 크롤링하여 저장합니다'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='실제 저장하지 않고 결과만 출력'
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=1.0,
            help='요청 간 지연 시간(초), 기본값: 1.0'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        delay = options['delay']

        hospitals = Hospital.objects.all()
        total_count = hospitals.count()
        success_count = 0
        skip_count = 0
        error_count = 0

        self.stdout.write(f'총 {total_count}개 병원의 태그 정보를 크롤링합니다...')

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN 모드: 실제 저장하지 않습니다'))

        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

        for hospital in tqdm(hospitals, desc="태그 크롤링"):
            try:
                url = f"https://www.eroum.co.kr/search/hospitalDetail?careCenterType=NURSING_HOSPITAL&ykiho={hospital.code}&webYn=Y"

                response = session.get(url, timeout=10)

                # URL이 없거나 404인 경우 스킵
                if response.status_code == 404:
                    skip_count += 1
                    self.stdout.write(f'SKIP: {hospital.name} ({hospital.code}) - 페이지 없음')
                    time.sleep(delay)
                    continue

                response.raise_for_status()

                soup = BeautifulSoup(response.text, 'html.parser')

                # 태그를 포함하는 div 찾기
                tag_elements = soup.find_all('span', class_='badge_order')

                if not tag_elements:
                    skip_count += 1
                    self.stdout.write(f'SKIP: {hospital.name} ({hospital.code}) - 태그 없음')
                    time.sleep(delay)
                    continue

                # 태그 텍스트 추출
                tag_names = []
                for tag_element in tag_elements:
                    tag_text = tag_element.get_text(strip=True)
                    if tag_text:
                        tag_names.append(tag_text)

                if not tag_names:
                    skip_count += 1
                    self.stdout.write(f'SKIP: {hospital.name} ({hospital.code}) - 유효한 태그 없음')
                    time.sleep(delay)
                    continue

                if not dry_run:
                    with transaction.atomic():
                        # 기존 태그 관계 제거
                        hospital.tags.clear()

                        # 태그 생성 또는 가져오기 및 관계 설정
                        for tag_name in tag_names:
                            tag, created = Tag.objects.get_or_create(name=tag_name)
                            hospital.tags.add(tag)

                            if created:
                                self.stdout.write(f'  새 태그 생성: {tag_name}')

                success_count += 1
                self.stdout.write(
                    f'SUCCESS: {hospital.name} ({hospital.code}) - 태그: {", ".join(tag_names)}'
                )

                time.sleep(delay)

            except requests.exceptions.RequestException as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(f'ERROR: {hospital.name} ({hospital.code}) - 네트워크 오류: {e}')
                )
                time.sleep(delay)

            except Exception as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(f'ERROR: {hospital.name} ({hospital.code}) - {e}')
                )
                time.sleep(delay)

        # 결과 요약
        self.stdout.write('\n' + '='*50)
        self.stdout.write(f'크롤링 완료')
        self.stdout.write(f'총 처리: {total_count}개')
        self.stdout.write(f'성공: {success_count}개')
        self.stdout.write(f'스킵: {skip_count}개')
        self.stdout.write(f'오류: {error_count}개')

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN 모드였습니다. 실제 저장되지 않았습니다.'))
