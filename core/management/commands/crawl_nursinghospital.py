import asyncio
import random
import os
import requests
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse
from django.core.files.base import ContentFile

from django.core.management.base import BaseCommand
from django.db import transaction
from core import models as core_models
import re
from asgiref.sync import sync_to_async

from bs4 import BeautifulSoup
from tqdm import tqdm

SEARCH_BASE_URL = "https://www.seniortalktalk.com/search"
DEFAULT_QUERY = {
    "kind": "요양병원",
    "keyword": "",
    "location": "서울시/전체",
    "sort": "평가등급 순",
    "filter": "",
}

# 세부 페이지 a 태그 href 패턴 후보들 (실제 DOM 미확인 환경 대응용)
DETAIL_KEYWORDS = ["detail", "facility", "nursing", "home", "center", "search/view"]

# 풍부도 점수 계산 헬퍼
def _compute_richness(data: dict) -> int:
    overview = data.get('overview') or {}
    bed_count = data.get('bed_count') or {}
    operation_facility = data.get('operation_facility') or {}
    doctor_count = data.get('doctor_count') or {}
    specialist_by_department = data.get('specialist_by_department') or {}
    department_specialists = data.get('department_specialists') or {}
    other_staff = data.get('other_staff') or {}
    consultation_hours = data.get('consultation_hours') or {}
    medical_fee_info = data.get('medical_fee_info') or {}

    score = 0
    score += sum(1 for v in overview.values() if v not in (None, '', []))
    score += len(bed_count) * 2  # 병상 정보 가중치
    score += len(operation_facility)
    score += len(doctor_count) * 3  # 의사 정보 가중치
    score += len(specialist_by_department) * 2
    score += len(department_specialists) * 2
    score += len(other_staff)
    score += len(consultation_hours) * 2  # 진료시간 정보 가중치
    score += len(medical_fee_info) * 2  # 진료비 정보 가중치
    return int(score * 100)  # 소수 방지

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.1 Safari/537.36"
)

RETRY_COUNT = 3
GOTO_TIMEOUT = 60000  # 60s
SCREENSHOT_DIR = Path('crawl_debug')
SCREENSHOT_DIR.mkdir(exist_ok=True)


class Command(BaseCommand):
    help = "시니어톡톡 요양병원 목록 + 디테일 크롤링 후 CSV 저장"

    def add_arguments(self, parser):
        parser.add_argument("--location", default="전체", help="검색 위치 파라미터 (기본: 전체 - 모든 지역 순회)")
        parser.add_argument("--max-pages", type=int, default=50, help="각 지역별 최대 크롤 페이지 수 (기본:50)")
        parser.add_argument("--delay", type=float, default=1.0, help="각 요청 사이 기본 지연(초)")
        parser.add_argument("--headful", action="store_true", help="브라우저 UI 표시")
        # CSV / detail-url 옵션 제거 및 최소 옵션 유지
        parser._actions = [a for a in parser._actions if a.dest not in {"output","no_csv","detail_url"}]
        # 안전하게 남은 help 수정
        for a in parser._actions:
            if a.dest == 'max_pages':
                a.help = '각 지역별 최대 크롤 페이지 수'

    def handle(self, *args, **options):
        try:
            asyncio.run(self._async_handle(options))
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("사용자 중단"))

    async def _async_handle(self, options):
        from playwright.async_api import async_playwright  # 지연 import

        location = options["location"]
        max_pages = options["max_pages"]
        delay = options["delay"]
        headless = not options["headful"]

        # 전국 지역 리스트
        all_locations = [
            "서울시/전체", "부산시/전체", "대구시/전체", "인천시/전체",
            "광주시/전체", "대전시/전체", "울산시/전체", "세종시/전체",
            "경기도/전체", "강원도/전체", "충청북도/전체", "충청남도/전체",
            "전라북도/전체", "전라남도/전체", "경상북도/전체", "경상남도/전체",
            "제주도/전체"
        ]

        # 특정 지역 지정시 해당 지역만, 아니면 전체 지역 순회
        if location != "전체":
            locations_to_crawl = [location if "/" in location else f"{location}/전체"]
        else:
            locations_to_crawl = all_locations

        saved_facilities = []
        detail_urls_seen = set()
        best_scores = {}  # code -> richness score
        dup_skipped = 0
        dup_updated = 0
        total_regions = len(locations_to_crawl)

        self.stdout.write(f"크롤링 대상 지역: {total_regions}개")
        self.stdout.write(f"각 지역별 최대 페이지: {max_pages}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless, args=["--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(
                user_agent=USER_AGENT,
                locale="ko-KR",
                java_script_enabled=True,
                extra_http_headers={
                    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Referer": "https://www.seniortalktalk.com/",
                },
                viewport={"width":1280,"height":1600}
            )
            # 리소스 절약: 이미지/폰트 차단
            async def route_intercept(route, request):
                if request.resource_type in ['image','media','font']:
                    await route.abort()
                else:
                    await route.continue_()
            await context.route("**/*", route_intercept)
            page = await context.new_page()

            async def safe_goto(pg, url, expect_selector=None):
                last_err = None
                for attempt in range(1, RETRY_COUNT+1):
                    try:
                        await pg.goto(url, wait_until='domcontentloaded', timeout=GOTO_TIMEOUT)
                        if expect_selector:
                            try:
                                await pg.wait_for_selector(expect_selector, timeout=8000)
                            except Exception:
                                pass
                        return True
                    except Exception as e:
                        last_err = e
                        self.stderr.write(f"[목록 이동 실패 {attempt}/{RETRY_COUNT}] {e}")
                        await asyncio.sleep(2*attempt)
                if last_err:
                    fname = SCREENSHOT_DIR / f"fail_list_{int(asyncio.get_event_loop().time())}.png"
                    try:
                        await pg.screenshot(path=str(fname))
                    except Exception:
                        pass
                return False

            async def safe_detail(detail_ctx, durl):
                dpage = await detail_ctx.new_page()
                for attempt in range(1, RETRY_COUNT+1):
                    try:
                        await dpage.goto(durl, wait_until='domcontentloaded', timeout=GOTO_TIMEOUT)
                        await dpage.wait_for_timeout(500)
                        # 페이지 내 간단 anchor 수 기록
                        try:
                            await dpage.evaluate("() => window.scrollTo(0,0)")
                        except Exception:
                            pass
                        return dpage
                    except Exception as e:
                        self.stderr.write(f"[상세 이동 실패 {attempt}/{RETRY_COUNT}] {durl} : {e}")
                        if attempt == RETRY_COUNT:
                            try:
                                await dpage.screenshot(path=str(SCREENSHOT_DIR / f"fail_detail_{int(asyncio.get_event_loop().time())}.png"))
                            except Exception:
                                pass
                        await asyncio.sleep(1.5*attempt)
                await dpage.close()
                return None

            async def auto_scroll(pg, max_rounds=8, pause=600):
                last_height = await pg.evaluate("() => document.body.scrollHeight")
                for i in range(max_rounds):
                    await pg.evaluate("() => window.scrollBy(0, document.body.scrollHeight)")
                    await pg.wait_for_timeout(pause)
                    new_height = await pg.evaluate("() => document.body.scrollHeight")
                    if new_height == last_height:
                        break
                    last_height = new_height

            # 지역별 순회
            for region_idx, current_location in enumerate(locations_to_crawl, 1):
                self.stdout.write(f"\n{'='*60}")
                self.stdout.write(f"[{region_idx}/{total_regions}] {current_location} 크롤링 시작")
                self.stdout.write(f"{'='*60}")

                region_facilities = 0
                empty_page_count = 0

                # 해당 지역의 페이지별 순회
                for page_no in range(1, max_pages + 1):
                    query = DEFAULT_QUERY.copy()
                    query["location"] = current_location
                    query["page"] = page_no

                    url = f"{SEARCH_BASE_URL}?{urlencode(query, doseq=True)}"
                    self.stdout.write(f"[{current_location}] 페이지 {page_no} 이동: {url}")

                    ok = await safe_goto(page, url, expect_selector='a')
                    if not ok:
                        continue

                    # 자동 스크롤 수행 (동적 로딩 대비)
                    await auto_scroll(page)
                    html = await page.content()

                    # 디버그 스냅샷 저장
                    region_name = current_location.split('/')[0]
                    debug_path = SCREENSHOT_DIR / f"{region_name}_page{page_no}.html"
                    debug_path.write_text(html, encoding='utf-8')

                    soup = BeautifulSoup(html, "lxml")

                    # 후보: list, item, card 등 class 를 가진 a 태그 수집 (일반화)
                    anchors = []
                    for a in soup.find_all("a", href=True):
                        href_lower = a["href"].lower()
                        if "/search/view/" in href_lower:  # 우선 강제 패턴
                            anchors.append(a)
                        elif any(k in href_lower for k in DETAIL_KEYWORDS):
                            anchors.append(a)

                    # 중복 제거 & 절대 URL 보정
                    detail_links = []
                    for a in anchors:
                        href = a["href"].strip()
                        if href.startswith("javascript:"):
                            continue
                        if href.startswith("/"):
                            href = "https://www.seniortalktalk.com" + href
                        if href not in detail_urls_seen and href.startswith("http"):
                            detail_urls_seen.add(href)
                            detail_links.append(href)

                    # 링크 디버그 저장
                    link_debug_file = SCREENSHOT_DIR / f"{region_name}_links_page{page_no}.txt"
                    link_debug_file.write_text("\n".join(detail_links), encoding='utf-8')

                    if not detail_links:
                        empty_page_count += 1
                        self.stdout.write(f"[{current_location}] 페이지 {page_no} 상세 링크 0개")
                        # 연속 3페이지 이상 비어있으면 해당 지역 크롤링 종료
                        if empty_page_count >= 3:
                            self.stdout.write(f"[{current_location}] 연속 {empty_page_count}페이지 비어있음 - 해당 지역 크롤링 종료")
                            break
                        continue
                    else:
                        empty_page_count = 0  # 링크가 있으면 카운터 리셋
                        self.stdout.write(f"[{current_location}] 페이지 {page_no} 상세 링크 {len(detail_links)}개")

                    page_facilities = 0
                    for link in tqdm(detail_links, desc=f"{region_name} p{page_no}", unit="fac"):
                        dpage = await safe_detail(context, link)
                        if not dpage:
                            continue
                        try:
                            dhtml = await dpage.content()
                            dsoup = BeautifulSoup(dhtml, "lxml")
                            data = self.parse_detail(dsoup, link)
                            code = data.get('overview', {}).get('code')
                            richness = _compute_richness(data)
                            do_save = True
                            updated = False
                            if code in best_scores:
                                if richness > best_scores[code]:
                                    updated = True
                                else:
                                    do_save = False
                            if do_save:
                                facility = await sync_to_async(self.save_to_db, thread_sensitive=True)(data)
                                best_scores[code] = richness
                                if facility:
                                    # 병원 정보 저장 후 이미지와 태그 크롤링
                                    try:
                                        images_found = await sync_to_async(self.crawl_hospital_images_and_tags, thread_sensitive=True)(facility)
                                        # has_images 필드 업데이트
                                        facility.has_images = images_found
                                        await sync_to_async(facility.save, thread_sensitive=True)(update_fields=['has_images'])
                                    except Exception as img_e:
                                        self.stderr.write(f"[이미지 크롤링 오류] {facility.code}: {img_e}")

                                    if updated:
                                        dup_updated += 1
                                        self.stdout.write(f"[갱신] {facility.code} (점수 {richness})")
                                    else:
                                        saved_facilities.append(facility)
                                        page_facilities += 1
                                        region_facilities += 1
                                        self.stdout.write(f"[저장] {facility.code} (점수 {richness})")
                            else:
                                dup_skipped += 1
                                self.stdout.write(f"[중복-스킵] {code} (기존 점수 {best_scores[code]}, 새 점수 {richness})")
                        except Exception as e:
                            self.stderr.write(f"[오류] {link}: {e}\n")
                        finally:
                            await dpage.close()
                            await asyncio.sleep(delay + random.uniform(0, delay / 2))

                    self.stdout.write(f"[{current_location}] 페이지 {page_no} 완료: {page_facilities}개 시설 저장")

                self.stdout.write(f"[{current_location}] 지역 크롤링 완료: 총 {region_facilities}개 시설")

            await context.close()
            await browser.close()

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"전체 크롤링 완료!")
        self.stdout.write(f"총 {len({f.id for f in saved_facilities})}개 시설 DB 저장")
        self.stdout.write(f"중복 스킵: {dup_skipped}, 정보 갱신: {dup_updated}")
        self.stdout.write(f"{'='*60}")
        try:
            hospital_count = await sync_to_async(core_models.Hospital.objects.count)()
            self.stdout.write(f"요양병원 레코드 누적: {hospital_count}")
        except Exception:
            pass

    def parse_detail(self, soup, url):
        """요양병원 상세 페이지 파싱"""
        data = {
            'overview': {},
            'bed_count': {},
            'operation_facility': {},
            'doctor_count': {},
            'specialist_by_department': {},
            'department_specialists': {},
            'other_staff': {},
            'consultation_hours': {},
            'medical_fee_info': {}
        }

        try:
            # URL에서 실제 병원 코드 추출
            # URL 형태: https://www.seniortalktalk.com/search/view/28/JDQ4MTYyMiM4MSMkMSMkOCMkOTkkNTgxMzUxIzExIyQxIyQzIyQ4OSQzNjEwMDIjNTEjJDEjJDIjJDgz?...
            code_match = re.search(r'/search/view/\d+/([A-Za-z0-9+/=]+)', url)
            if code_match:
                data['overview']['code'] = code_match.group(1)
            else:
                # 백업: URL을 해시해서 고유 코드로 사용
                import hashlib
                url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
                data['overview']['code'] = f"hosp_{url_hash}"
                self.stdout.write(f"코드 추출 실패, 임시 코드 생성: {data['overview']['code']} for {url}")

            # 병원명 파싱
            name_elem = soup.select_one('em.fst-normal')
            if name_elem:
                data['overview']['name'] = name_elem.get_text(strip=True)

            # 디버깅: 추출된 정보 출력
            self.stdout.write(f"파싱된 데이터: 코드={data['overview'].get('code')}, 이름={data['overview'].get('name')}")

            # 등급 파싱
            grade_elem = soup.select_one('.section-view-grade')
            if grade_elem:
                data['overview']['grade'] = grade_elem.get_text(strip=True)

            # 기본 정보 파싱 (설립구분, 전화번호, 설립일자)
            basic_info_dl = soup.select('dl.row.m-0.mt-3')
            if basic_info_dl:
                dt_elements = basic_info_dl[0].select('dt')
                dd_elements = basic_info_dl[0].select('dd')

                for dt, dd in zip(dt_elements, dd_elements):
                    key = dt.get_text(strip=True)
                    value = dd.get_text(strip=True)

                    if key == '설립구분':
                        data['overview']['establishment_type'] = value
                    elif key == '전화번호':
                        data['overview']['phone'] = value
                    elif key == '설립일자':
                        data['overview']['establishment_date'] = value

            # 병상수 파싱
            bed_section = soup.find('h5', string='병상수')
            if bed_section:
                bed_dl = bed_section.find_next_sibling('dl')
                if bed_dl:
                    dt_elements = bed_dl.select('dt')
                    dd_elements = bed_dl.select('dd')

                    for dt, dd in zip(dt_elements, dd_elements):
                        bed_type = dt.get_text(strip=True)
                        bed_info = dd.get_text(strip=True)
                        data['bed_count'][bed_type] = bed_info

            # 운영/시설 파싱
            operation_section = soup.find('h5', string='운영/시설')
            if operation_section:
                operation_dl = operation_section.find_next_sibling('dl')
                if operation_dl:
                    dt_elements = operation_dl.select('dt')
                    dd_elements = operation_dl.select('dd')

                    for dt, dd in zip(dt_elements, dd_elements):
                        key = dt.get_text(strip=True)
                        value = dd.get_text(strip=True)
                        data['operation_facility'][key] = value

            # 의사수 파싱
            doctor_section = soup.find('h5', string='의사수')
            if doctor_section:
                doctor_dl = doctor_section.find_next_sibling('dl')
                if doctor_dl:
                    dt_elements = doctor_dl.select('dt')
                    dd_elements = doctor_dl.select('dd')

                    for dt, dd in zip(dt_elements, dd_elements):
                        doctor_type = dt.get_text(strip=True)
                        doctor_count = dd.get_text(strip=True)
                        data['doctor_count'][doctor_type] = doctor_count

            # 전문과목별(전문의수) 파싱
            specialist_section = soup.find('h5', string='전문과목별(전문의수)')
            if specialist_section:
                specialist_dl = specialist_section.find_next_sibling('dl')
                if specialist_dl:
                    dt_elements = specialist_dl.select('dt')
                    dd_elements = specialist_dl.select('dd')

                    for dt, dd in zip(dt_elements, dd_elements):
                        department = dt.get_text(strip=True)
                        count = dd.get_text(strip=True)
                        data['specialist_by_department'][department] = count

            # 진료과목별(전문의수) 파싱
            department_section = soup.find('h5', string='진료과목별(전문의수)')
            if department_section:
                department_dl = department_section.find_next_sibling('dl')
                if department_dl:
                    dt_elements = department_dl.select('dt')
                    dd_elements = department_dl.select('dd')

                    for dt, dd in zip(dt_elements, dd_elements):
                        department = dt.get_text(strip=True)
                        count = dd.get_text(strip=True)
                        data['department_specialists'][department] = count

            # 기타인력 파싱
            other_staff_section = soup.find('h4', string='기타인력')
            if other_staff_section:
                # section-view-content2 div 내의 dl 요소 찾기
                content_div = other_staff_section.find_next_sibling('div', class_='section-view-content2')
                if content_div:
                    staff_dl = content_div.select_one('dl')
                    if staff_dl:
                        dt_elements = staff_dl.select('dt')
                        dd_elements = staff_dl.select('dd')

                        for dt, dd in zip(dt_elements, dd_elements):
                            staff_type = dt.get_text(strip=True)
                            staff_count = dd.get_text(strip=True)
                            data['other_staff'][staff_type] = staff_count

            # 진료시간 파싱
            consultation_section = soup.find('h4', string='진료시간')
            if consultation_section:
                content_div = consultation_section.find_next_sibling('div', class_='section-view-content2')
                if content_div:
                    # 기본 진료시간
                    main_dl = content_div.select_one('dl')
                    if main_dl:
                        dt_elements = main_dl.select('dt')
                        dd_elements = main_dl.select('dd')

                        for dt, dd in zip(dt_elements, dd_elements):
                            day = dt.get_text(strip=True)
                            time = dd.get_text(strip=True)
                            data['consultation_hours'][day] = time

                    # 점심시간 파싱
                    lunch_h5 = content_div.find('h5', string='점심시간')
                    if lunch_h5:
                        lunch_dl = lunch_h5.find_next_sibling('dl')
                        if lunch_dl:
                            dt_elements = lunch_dl.select('dt')
                            dd_elements = lunch_dl.select('dd')

                            for dt, dd in zip(dt_elements, dd_elements):
                                day = dt.get_text(strip=True)
                                time = dd.get_text(strip=True)
                                data['consultation_hours'][f"점심시간_{day}"] = time

            # 진료비정보 파싱
            medical_fee_section = soup.find('h4', string='진료비정보')
            if medical_fee_section:
                content_div = medical_fee_section.find_next_sibling('div', class_='section-view-content2')
                if content_div:
                    # 모든 h5 섹션 처리
                    h5_sections = content_div.find_all('h5')
                    for h5 in h5_sections:
                        category = h5.get_text(strip=True)
                        dl = h5.find_next_sibling('dl')
                        if dl:
                            dt_elements = dl.select('dt')
                            dd_elements = dl.select('dd')

                            for dt, dd in zip(dt_elements, dd_elements):
                                item_name = dt.get_text(strip=True)
                                fee = dd.get_text(strip=True)
                                # 카테고리_항목명 형태로 저장
                                key = f"{category}_{item_name}"
                                data['medical_fee_info'][key] = fee

                    # h5가 없는 직접적인 dl도 처리 (첫 번째 dl)
                    first_dl = content_div.select_one('dl')
                    if first_dl:
                        # 이미 h5 섹션으로 처리되지 않은 경우만
                        prev_h5 = first_dl.find_previous_sibling('h5')
                        if not prev_h5:
                            dt_elements = first_dl.select('dt')
                            dd_elements = first_dl.select('dd')

                            for dt, dd in zip(dt_elements, dd_elements):
                                item_name = dt.get_text(strip=True)
                                fee = dd.get_text(strip=True)
                                data['medical_fee_info'][item_name] = fee

            # 위치정보 파싱
            location_section = soup.find('h4', string='위치')
            if location_section:
                location_div = location_section.find_next_sibling('div', class_='section-view-content')
                if location_div:
                    location_p = location_div.select_one('p')
                    if location_p:
                        data['overview']['location'] = location_p.get_text(strip=True)

            # 지역 정보 추출 (breadcrumb이나 다른 요소에서)
            # 기본적으로는 크롤링 매개변수에서 가져오지만, 페이지에서도 시도해볼 수 있음
            # 추후 필요시 구현

        except Exception as e:
            self.stderr.write(f"파싱 오류 ({url}): {e}")

        return data

    @transaction.atomic
    def save_to_db(self, data):
        """요양병원 데이터를 데이터베이스에 저장"""
        try:
            overview = data.get('overview', {})
            code = overview.get('code')

            if not code:
                self.stderr.write("병원 코드가 없어 저장을 건너뜁니다.")
                return None

            # 설립일자 처리
            establishment_date = None
            if overview.get('establishment_date'):
                try:
                    from datetime import datetime
                    establishment_date = datetime.strptime(overview['establishment_date'], '%Y-%m-%d').date()
                except:
                    # 날짜 형식이 다를 수 있으므로 다른 형식도 시도
                    try:
                        establishment_date = datetime.strptime(overview['establishment_date'], '%Y.%m.%d').date()
                    except:
                        pass

            hospital, created = core_models.Hospital.objects.update_or_create(
                code=code,
                defaults={
                    'name': overview.get('name', ''),
                    'grade': overview.get('grade', ''),
                    'establishment_type': overview.get('establishment_type', ''),
                    'phone': overview.get('phone', ''),
                    'establishment_date': establishment_date,
                    'bed_count': data.get('bed_count', {}),
                    'operation_facility': data.get('operation_facility', {}),
                    'doctor_count': data.get('doctor_count', {}),
                    'specialist_by_department': data.get('specialist_by_department', {}),
                    'department_specialists': data.get('department_specialists', {}),
                    'other_staff': data.get('other_staff', {}),
                    'consultation_hours': data.get('consultation_hours', {}),
                    'medical_fee_info': data.get('medical_fee_info', {}),
                    'location': overview.get('location', ''),
                    'has_images': False,  # 추후 이미지 크롤링 시 구현
                    'sido': '',  # 추후 지역 정보 파싱 시 구현
                    'sigungu': '',  # 추후 지역 정보 파싱 시 구현
                    'homepage_url': '',  # 추후 홈페이지 정보 파싱 시 구현
                    'summary': ''  # 추후 AI 요약 시 구현
                }
            )

            return hospital

        except Exception as e:
            self.stderr.write(f"DB 저장 오류: {e}")
            return None

    def crawl_hospital_images_and_tags(self, hospital):
        """병원 코드를 사용해 eroum.co.kr에서 이미지와 태그 크롤링"""
        # 요양병원의 경우 careCenterType을 NURSING_HOSPITAL로 변경
        url = f"https://eroum.co.kr/search/hospitalDetail?careCenterType=NURSING_HOSPITAL&webYn=Y&ykiho={hospital.code}"

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
            images_found = self.crawl_hospital_images(hospital, soup)

            # 태그 크롤링
            self.crawl_hospital_tags(hospital, soup)

            return images_found

        except Exception as e:
            self.stderr.write(f"이미지/태그 크롤링 오류 ({hospital.code}): {e}")
            return False

    def crawl_hospital_images(self, hospital, soup):
        """이미지 크롤링 및 저장 - 이미지가 발견되면 True 반환"""
        # swiper-slide 내의 이미지 찾기
        image_slides = soup.select('div.swiper-slide img')

        if not image_slides:
            return False

        images_saved = 0
        for img_tag in image_slides:
            img_src = img_tag.get('src')
            if not img_src:
                continue

            try:
                # 이미 존재하는 이미지인지 확인
                if core_models.HospitalImage.objects.filter(original_url=img_src).exists():
                    continue

                # 이미지 다운로드
                img_response = requests.get(img_src, headers={'User-Agent': USER_AGENT}, timeout=15)
                img_response.raise_for_status()

                # 파일명 생성
                parsed_url = urlparse(img_src)
                filename = os.path.basename(parsed_url.path)
                if not filename or '.' not in filename:
                    filename = f"hospital_{hospital.code}_{images_saved}.jpg"

                # HospitalImage 객체 생성 및 이미지 저장
                hospital_image = core_models.HospitalImage(
                    hospital=hospital,
                    original_url=img_src
                )

                # 이미지 파일을 ImageField에 저장
                hospital_image.image.save(
                    filename,
                    ContentFile(img_response.content),
                    save=True
                )

                images_saved += 1
                self.stdout.write(f"이미지 저장 완료: {hospital.code} - {img_src}")

            except Exception as e:
                self.stderr.write(f"이미지 저장 실패 ({img_src}): {e}")
                continue

        return images_saved > 0

    def crawl_hospital_tags(self, hospital, soup):
        """태그 크롤링 및 저장"""
        # 태그 관련 요소 찾기 (실제 HTML 구조에 따라 조정 필요)
        tag_elements = soup.select('.tag, .badge, .label, [class*="tag"]')

        if not tag_elements:
            return

        for tag_elem in tag_elements:
            tag_text = tag_elem.get_text(strip=True)
            if not tag_text or len(tag_text) > 50:  # 너무 긴 텍스트는 태그가 아닐 가능성
                continue

            try:
                # 태그 생성 또는 가져오기
                tag, created = core_models.Tag.objects.get_or_create(name=tag_text)

                # 병원과 태그 연결
                hospital.tags.add(tag)

                if created:
                    self.stdout.write(f"새 태그 생성: {tag_text}")

            except Exception as e:
                self.stderr.write(f"태그 저장 실패 ({tag_text}): {e}")
                continue

