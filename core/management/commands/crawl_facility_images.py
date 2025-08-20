import asyncio
import os
import requests
from urllib.parse import urljoin, urlparse
from pathlib import Path
from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django.db import transaction
from core.models import Facility, FacilityImage, Tag
from bs4 import BeautifulSoup
from tqdm import tqdm
import time
import random

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.1 Safari/537.36"
)

class Command(BaseCommand):
    help = "기존 DB의 Facility 코드를 사용해 eroum.co.kr에서 ���미지와 태그를 크롤링하여 저장"

    def add_arguments(self, parser):
        parser.add_argument("--facility-code", help="특정 시설 코드만 크롤링")
        parser.add_argument("--limit", type=int, default=None, help="크롤링할 시설 수 제한")
        parser.add_argument("--delay", type=float, default=2.0, help="요청 간 지연시간(초)")

    def handle(self, *args, **options):
        facility_code = options.get('facility_code')
        limit = options.get('limit')
        delay = options.get('delay')

        # 크롤링할 시설 선택
        if facility_code:
            facilities = Facility.objects.filter(code=facility_code)
            if not facilities.exists():
                self.stdout.write(self.style.ERROR(f"시설 코드 {facility_code}를 찾을 수 없습니다."))
                return
        else:
            facilities = Facility.objects.all()
            if limit:
                facilities = facilities[:limit]

        self.stdout.write(f"총 {facilities.count()}개 시설 크롤링 시작")

        success_count = 0
        error_count = 0

        for facility in tqdm(facilities, desc="시설 크롤링"):
            try:
                self.crawl_facility_detail(facility, delay)
                success_count += 1
                self.stdout.write(f"[성공] {facility.code} - {facility.name}")
            except Exception as e:
                error_count += 1
                self.stderr.write(f"[오류] {facility.code}: {e}")

            # 지연
            time.sleep(delay + random.uniform(0, delay/2))

        self.stdout.write(f"\n크롤링 완료: 성공 {success_count}, 실패 {error_count}")

    def crawl_facility_detail(self, facility, delay):
        """개별 시설의 상세 페이지를 크롤링하여 이미지와 태그 저장"""
        url = f"https://eroum.co.kr/search/detail?careCenterType=NURSING_HOME&webYn=&ltcAdminSym={facility.code}"

        headers = {
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }

        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # 이미지 크롤링
            images_found = self.crawl_images(facility, soup)

            # 태그 크롤링
            self.crawl_tags(facility, soup)

            # has_images 필드 업데이�� (URL 유효하고 이미지가 있으면 True)
            facility.has_images = images_found
            facility.save(update_fields=['has_images'])

        except Exception as e:
            # URL이 유효하지 않거나 오류 발생시 False로 설정
            facility.has_images = False
            facility.save(update_fields=['has_images'])
            raise e

    def crawl_images(self, facility, soup):
        """이미지 크롤링 및 저장 - 이미지가 발견되면 True 반환"""
        # swiper-slide 내의 이미지 찾기
        image_slides = soup.select('div.swiper-slide img')

        images_saved = False

        for img_tag in image_slides:
            img_src = img_tag.get('src')
            if not img_src:
                continue

            # 절대 URL로 변환
            if img_src.startswith('//'):
                img_src = 'https:' + img_src
            elif img_src.startswith('/'):
                img_src = 'https://eroum.co.kr' + img_src
            elif not img_src.startswith('http'):
                continue

            # 이미 존재하는 이미지인지 확인
            if FacilityImage.objects.filter(original_url=img_src).exists():
                images_saved = True  # 이미 저장된 이미지라도 이미지가 있다는 뜻
                continue

            try:
                # 이미지 다운로드
                img_response = requests.get(img_src, headers={'User-Agent': USER_AGENT}, timeout=30)
                img_response.raise_for_status()

                # 파일명 생성
                parsed_url = urlparse(img_src)
                file_name = os.path.basename(parsed_url.path)
                if not file_name or '.' not in file_name:
                    file_name = f"{facility.code}_{int(time.time())}.jpg"

                # FacilityImage 객체 생성 및 저장
                facility_image = FacilityImage(
                    facility=facility,
                    original_url=img_src
                )

                # ContentFile로 이미지 저장
                facility_image.image.save(
                    file_name,
                    ContentFile(img_response.content),
                    save=True
                )

                images_saved = True
                self.stdout.write(f"  이미지 저장: {file_name}")

            except Exception as e:
                self.stderr.write(f"  이미지 다운로드 실패 {img_src}: {e}")

        return images_saved

    def crawl_tags(self, facility, soup):
        """태그(��지) 크롤링 및 저장"""
        # 배지 요소들 찾기
        badge_elements = soup.select('span.badge_order')

        if not badge_elements:
            return

        tags_to_add = []

        for badge in badge_elements:
            tag_name = badge.get_text(strip=True)
            if not tag_name:
                continue

            # 태그 생성 또는 가져오기
            tag, created = Tag.objects.get_or_create(name=tag_name)
            tags_to_add.append(tag)

            if created:
                self.stdout.write(f"  새 태그 생성: {tag_name}")

        # 시설에 태그 연결
        if tags_to_add:
            for tag in tags_to_add:
                tag.facilities.add(facility)

            tag_names = [tag.name for tag in tags_to_add]
            self.stdout.write(f"  태그 연결: {', '.join(tag_names)}")
