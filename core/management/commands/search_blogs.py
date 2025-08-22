import requests
import time
from django.core.management.base import BaseCommand
from django.conf import settings
from core.models import Facility, Blog


class Command(BaseCommand):
    help = '네이버 블로그 검색 API를 사용하여 각 시설의 블로그 글을 수집합니다.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='처리할 시설 수를 제한합니다 (테스트용)'
        )
        parser.add_argument(
            '--display',
            type=int,
            default=10,
            help='검색 결과 개수 (기본값: 10, 최대: 100)'
        )
        parser.add_argument(
            '--start',
            type=int,
            default=1,
            help='검색 시작 위치 (기본값: 1)'
        )

    def handle(self, *args, **options):
        # 네이버 API 키 확인
        client_id = settings.NAVER_CLIENT_ID
        client_secret = settings.NAVER_CLIENT_SECRET

        if not client_id or not client_secret:
            self.stdout.write(
                self.style.ERROR('NAVER_CLIENT_ID 또는 NAVER_CLIENT_SECRET이 설정되지 않았습니다.')
            )
            return

        # 시설 목록 가져오기
        facilities = Facility.objects.all()
        if options['limit']:
            facilities = facilities[:options['limit']]

        self.stdout.write(f'총 {facilities.count()}개 시설에 대해 블로그 검색을 시작합니다.')

        success_count = 0
        error_count = 0

        for facility in facilities:
            try:
                self.stdout.write(f'검색 중: {facility.name}')

                # 네이버 블로그 검색 API 호출
                results = self.search_naver_blog(
                    facility.name,
                    client_id,
                    client_secret,
                    options['display'],
                    options['start']
                )

                if results:
                    # 기존 블로그 데이터 삭제 (중복 방지)
                    Blog.objects.filter(facility=facility).delete()

                    # 새로운 블로그 데이터 저장
                    created_count = 0
                    for item in results:
                        blog, created = Blog.objects.get_or_create(
                            facility=facility,
                            link=item['link'],
                            defaults={
                                'title': self.clean_html_tags(item['title']),
                                'description': self.clean_html_tags(item['description']),
                                'bloggername': item.get('bloggername', ''),
                                'bloggerlink': item.get('bloggerlink', ''),
                                'postdate': item.get('postdate', ''),
                            }
                        )
                        if created:
                            created_count += 1

                    self.stdout.write(
                        self.style.SUCCESS(f'  → {created_count}개의 블로그 글을 저장했습니다.')
                    )
                    success_count += 1
                else:
                    self.stdout.write(
                        self.style.WARNING(f'  → 검색 결과가 없습니다.')
                    )

                # API 호출 제한을 위한 딜레이 (초당 10회 제한)
                time.sleep(0.1)

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'  → 오류 발생: {str(e)}')
                )
                error_count += 1
                continue

        self.stdout.write(
            self.style.SUCCESS(
                f'\n완료: 성공 {success_count}개, 실패 {error_count}개'
            )
        )

    def search_naver_blog(self, query, client_id, client_secret, display=10, start=1):
        """네이버 블로그 검색 API 호출"""
        url = "https://openapi.naver.com/v1/search/blog"

        headers = {
            'X-Naver-Client-Id': client_id,
            'X-Naver-Client-Secret': client_secret,
        }

        params = {
            'query': query,
            'display': min(display, 100),  # 최대 100개
            'start': start,
            'sort': 'date'  # 날짜순 정렬
        }

        try:
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=getattr(settings, 'NAVER_API_TIMEOUT', 5)
            )
            response.raise_for_status()

            data = response.json()
            return data.get('items', [])

        except requests.exceptions.RequestException as e:
            self.stdout.write(
                self.style.ERROR(f'API 호출 오류: {str(e)}')
            )
            return None
        except ValueError as e:
            self.stdout.write(
                self.style.ERROR(f'JSON 파싱 오류: {str(e)}')
            )
            return None

    def clean_html_tags(self, text):
        """HTML 태그 제거"""
        import re
        if not text:
            return ''
        # HTML 태그 제거
        clean_text = re.sub(r'<[^>]+>', '', text)
        # HTML 엔티티 디코딩
        clean_text = clean_text.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
        clean_text = clean_text.replace('&quot;', '"').replace('&#39;', "'")
        return clean_text.strip()
