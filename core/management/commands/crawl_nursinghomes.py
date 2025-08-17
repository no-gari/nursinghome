import asyncio
import random
import os
from pathlib import Path
from urllib.parse import urlencode

from django.core.management.base import BaseCommand
from django.db import transaction
from core import models as core_models
import re
from asgiref.sync import sync_to_async

from bs4 import BeautifulSoup
from tqdm import tqdm

SEARCH_BASE_URL = "https://www.seniortalktalk.com/search"
DEFAULT_QUERY = {
    "kind": "요양원",
    "keyword": "",
    "location": "서울시/전체",
    "sort": "평가등급 순",
    "filter": "",
}

# 세부 페이지 a 태그 href 패턴 후보들 (실제 DOM 미확인 환경 대응용)
DETAIL_KEYWORDS = ["detail", "facility", "nursing", "home", "center", "search/view"]

# 풍부도 점수 계산 헬퍼
def _compute_richness(data: dict) -> int:
    ov = data.get('overview') or {}
    eval_items = data.get('evaluation_items') or []
    basic_items = data.get('basic_items') or []
    staff_items = data.get('staff_items') or []
    program_items = data.get('program_items') or []
    location_items = data.get('location_items') or []
    noncov_items = data.get('non_covered_items') or []
    score = 0
    score += sum(1 for v in ov.values() if v not in (None, '', []))
    score += len(basic_items)
    score += len(eval_items) * 2  # 평가 항목 가중치
    score += len(staff_items)
    score += len(program_items)
    score += len(location_items) * 3  # 위치 정보 항목별 가중치
    score += len(noncov_items) * 2  # 비급여 항목 가중치
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
    help = "시니어톡톡 요양원 목록 + 디테일 크롤링 후 CSV 저장"

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
            eval_count = await sync_to_async(core_models.FacilityEvaluation.objects.count)()
            self.stdout.write(f"평가 레코드 누적: {eval_count}")
        except Exception:
            pass

    def parse_detail(self, soup: BeautifulSoup, url: str) -> dict:
        # 기존 전역 텍스트 기반 로직 이전에 시설 영역을 우선 파싱
        container = soup.select_one('.section-view-title')
        raw_text_all = soup.get_text(" ", strip=True)
        data = {"raw_text": raw_text_all}
        # 코드 추출 (view 경로에서 숫자)
        m_code = re.search(r"/view/[^/]+/(\d+)", url)
        if not m_code:
            m_code = re.search(r"/(\d{6,})", url)
        code = m_code.group(1) if m_code else url
        overview = {"code": code}
        if container:
            # kind (data-kind)
            kind = container.get('data-kind') or ''
            if kind:
                overview['kind'] = kind.strip()
            # grade
            grade_el = container.select_one('.section-view-grade')
            if grade_el:
                overview['grade'] = grade_el.get_text(strip=True)
            # name
            name_el = container.select_one('h3 em') or container.select_one('h3')
            if name_el:
                name_text = name_el.get_text(strip=True)
                # 사이트명(시니어톡톡) 오탐 방지: 시설명에 공백/한글 다��� 포함 기대
                if name_text and name_text != '시니어톡톡':
                    overview['name'] = name_text
            # address (추��� 위치 모델에 활용 가능)
            addr_el = container.select_one('.section-view-address')
            if addr_el:
                overview['address'] = addr_el.get_text(strip=True)
            # dl dt/dd 쌍 처리
            dl = container.select_one('dl')
            if dl:
                dts = dl.find_all('dt')
                dds = dl.find_all('dd')
                for dt, dd in zip(dts, dds):
                    label = dt.get_text(strip=True)
                    value = dd.get_text(strip=True)
                    if not label:
                        continue
                    if label == '정원':
                        overview['capacity'] = self._parse_int(value)
                    elif label == '현원':
                        overview['occupancy'] = self._parse_int(value)
                    elif label == '대기':
                        overview['waiting'] = self._parse_int(value)
                    elif label in ('이용가능', '이용 가능'):
                        overview['availability'] = self._normalize_availability(value)
        # fallback: 이름이 비어있으면 title/h1/h2 검색 (기존 방식 유지)
        if 'name' not in overview:
            for sel in ['h1', 'h2', 'title']:
                el = soup.find(sel)
                if el:
                    txt = el.get_text(strip=True)
                    if txt and txt != '시니니어톡톡':
                        overview['name'] = txt
                        break
        data['overview'] = overview
        # 이하 기존 평가/인력 등 나머지 파싱은 일단 비활성(추후 섹션별 구현 예정)
        data['evaluation'] = {}
        data['staff'] = {}
        data['programs'] = {}
        data['location'] = {}
        data['non_covered'] = []
        data['overview']['raw_text'] = raw_text_all

        # 기본정보 섹션 파싱 (h4 '기본정보' 이후 .section-view-content2 내 첫번째 dl)
        basic_items = []
        basic_header = None
        for h4 in soup.select('h4'):
            if h4.get_text(strip=True) == '기본���보':
                basic_header = h4
                break
        if basic_header:
            # 형제/다음 요소에서 dl 찾기
            section = basic_header.find_next('div', class_='section-view-content2')
            if section:
                dl = section.find('dl')
                if dl:
                    dts = dl.find_all('dt')
                    dds = dl.find_all('dd')
                    for dt, dd in zip(dts, dds):
                        title_txt = dt.get_text(strip=True)
                        # dd 내부 a 태그가 있으면 href 우선, 없으면 텍스트
                        link = dd.find('a')
                        if link and link.get('href'):
                            content_txt = link.get('href').strip()
                        else:
                            content_txt = dd.get_text(strip=True)
                        if title_txt:
                            basic_items.append({'title': title_txt, 'content': content_txt})
        data['basic_items'] = basic_items
        # 평가정보 섹션 파싱 (h4 '평가정보')
        evaluation_items = []
        eval_header = None
        for h4 in soup.select('h4'):
            if h4.get_text(strip=True) == '평가정보':
                eval_header = h4
                break
        if eval_header:
            eval_section = eval_header.find_next('div', class_='section-view-content2')
            if eval_section:
                dl2 = eval_section.find('dl')
                if dl2:
                    dts2 = dl2.find_all('dt')
                    dds2 = dl2.find_all('dd')
                    for dt, dd in zip(dts2, dds2):
                        t = dt.get_text(strip=True)
                        c = dd.get_text(strip=True)
                        if t:
                            evaluation_items.append({'title': t, 'content': c})
        data['evaluation_items'] = evaluation_items
        # 인력현황 섹션 파싱 (h4 '인력현���')
        staff_items = []
        staff_header = None
        for h4 in soup.select('h4'):
            if h4.get_text(strip=True) == '인력현황':
                staff_header = h4
                break
        if staff_header:
            staff_section = staff_header.find_next('div', class_='section-view-content2')
            if staff_section:
                dl3 = staff_section.find('dl')
                if dl3:
                    dts3 = dl3.find_all('dt')
                    dds3 = dl3.find_all('dd')
                    for dt, dd in zip(dts3, dds3):
                        tt = dt.get_text(strip=True)
                        cc = dd.get_text(strip=True)
                        if tt:
                            staff_items.append({'title': tt, 'content': cc})
        data['staff_items'] = staff_items
        # 프로그램운영 섹션 파싱 (h4 '프로그램운영')
        program_items = []
        prog_header = None
        for h4 in soup.select('h4'):
            if h4.get_text(strip=True) == '프로그램운영':
                prog_header = h4
                break
        if prog_header:
            prog_section = prog_header.find_next('div', class_='section-view-content2')
            if prog_section:
                dlp = prog_section.find('dl')
                if dlp:
                    dts_p = dlp.find_all('dt')
                    dds_p = dlp.find_all('dd')
                    for dt, dd in zip(dts_p, dds_p):
                        pt = dt.get_text(strip=True)
                        pc_raw = dd.get_text(strip=True)
                        # 콤마 기준 분리 유지 대신 원문 보존
                        if pt:
                            program_items.append({'title': pt, 'content': pc_raw})
        data['program_items'] = program_items
        # 위치 섹션 파싱 (h4 '위치') - 개별 항목으로 분리
        location_items = []
        loc_header = None
        for h4 in soup.select('h4'):
            if h4.get_text(strip=True) == '위치':
                loc_header = h4
                break
        if loc_header:
            # 주소 p
            addr_block = loc_header.find_next('div', class_='section-view-content')
            if addr_block:
                addr_texts = []
                for p in addr_block.find_all('p'):
                    t = p.get_text(strip=True)
                    if t:
                        addr_texts.append(t)
                if addr_texts:
                    location_items.append({
                        'title': '주소',
                        'content': ' | '.join(addr_texts)
                    })

            # 교통/주차 dl - 각각 개별 항목으로 저장
            loc_section2 = loc_header.find_next('div', class_='section-view-content2')
            if loc_section2:
                dl_loc = loc_section2.find('dl')
                if dl_loc:
                    dts_l = dl_loc.find_all('dt')
                    dds_l = dl_loc.find_all('dd')
                    for dt, dd in zip(dts_l, dds_l):
                        label = dt.get_text(strip=True)
                        val = dd.get_text(strip=True)
                        if label and val:
                            location_items.append({
                                'title': label,
                                'content': val
                            })
        data['location_items'] = location_items
        # 홈페이지 섹션 파싱 (<b>홈페이지</b> 이후 첫 a href)
        homepage_item = None
        for b in soup.select('b'):
            if b.get_text(strip=True) == '홈페이지':
                a = b.find_next('a', href=True)
                if a:
                    # href 우선, 없으면 텍스트 (href 존재 명시)
                    href = a.get('href', '').strip()
                    if href:
                        homepage_item = {'title': '홈페이지', 'content': href}
                    else:
                        txt = a.get_text(strip=True)
                        if txt:
                            homepage_item = {'title': '홈페이지', 'content': txt}
                break
        data['homepage_item'] = homepage_item
        # 비급여 항목 섹션 파싱 (div.section-calc-label[data-focus="non_benefit"]) - 개별 항목으로 분리
        noncov_items = []
        label_div = soup.select_one('div.section-calc-label[data-focus="non_benefit"]')
        if label_div and '비급여 항목' in label_div.get_text():
            container_div = label_div.find_parent('div', class_='section-calc-content') or label_div.parent
            # 월 합계는 제외하고 개별 항목만 저장
            if container_div:
                for li in container_div.select('div.section-calc-item ul li'):
                    label = li.find('label')
                    if not label:
                        continue
                    text = label.get_text(" ", strip=True)
                    # 불필��한 다중 공백 정리
                    text = re.sub(r'\s+', ' ', text)
                    if text:
                        # 항목명과 금액을 분리
                        if ':' in text:
                            title_part, content_part = text.split(':', 1)
                            noncov_items.append({
                                'title': title_part.strip(),
                                'content': content_part.strip()
                            })
                        else:
                            # ':' 가 없는 경우 공백으로 분리 시도
                            parts = text.rsplit(' ', 1)
                            if len(parts) == 2 and '원' in parts[1]:
                                noncov_items.append({
                                    'title': parts[0].strip(),
                                    'content': parts[1].strip()
                                })
                            else:
                                # 분리할 수 없는 경우 전체를 title로
                                noncov_items.append({
                                    'title': text,
                                    'content': ''
                                })
        data['non_covered_items'] = noncov_items
        return data

    # 헬퍼: 숫자 파싱 (콤마 제거, '명' 제거)
    def _parse_int(self, text_val: str):
        if not text_val:
            return None
        cleaned = re.sub(r'[^0-9]', '', text_val)
        if not cleaned:
            return None
        try:
            return int(cleaned)
        except Exception:
            return None

    # 헬퍼: 이용가능 상태 정규화
    def _normalize_availability(self, val: str) -> str:
        v = (val or '').strip()
        if '가능' in v and ('불' not in v and '불가' not in v):
            return '가능'
        if '불가' in v or '불가능' in v or '마감' in v:
            return '불가능'
        return v

    def save_to_db(self, data: dict):
        ov = data.get('overview') or {}
        code = ov.get('code')
        if not code:
            return None
        name = ov.get('name') or code
        kind = ov.get('kind') or ''
        grade = ov.get('grade') or ''
        availability = ov.get('availability') or ''
        capacity = ov.get('capacity')
        occupancy = ov.get('occupancy')
        waiting = ov.get('waiting')

        from core.models import Facility, FacilityBasic  # 지연 import
        with transaction.atomic():
            facility, created = Facility.objects.get_or_create(code=code, defaults={
                'name': name,
                'kind': kind,
                'grade': grade,
                'availability': availability,
                'capacity': capacity,
                'occupancy': occupancy,
                'waiting': waiting,
            })
            # 업데이트 필요 필드만 반영
            changed = False
            for field, value in {
                'name': name,
                'kind': kind,
                'grade': grade,
                'availability': availability,
                'capacity': capacity,
                'occupancy': occupancy,
                'waiting': waiting,
            }.items():
                if value is not None and getattr(facility, field) != value:
                    setattr(facility, field, value)
                    changed = True
            if changed:
                facility.save()

            # 기본정보 항목 저장 (재생성)
            basic_items = data.get('basic_items') or []
            if basic_items:
                FacilityBasic.objects.filter(facility=facility).delete()
                FacilityBasic.objects.bulk_create([
                    FacilityBasic(facility=facility, title=item['title'][:100], content=item['content'])
                    for item in basic_items if item.get('title')
                ])
            # 평가정보 항목 저장 (재생성)
            from core.models import FacilityEvaluation
            eval_items = data.get('evaluation_items') or []
            if eval_items:
                FacilityEvaluation.objects.filter(facility=facility).delete()
                FacilityEvaluation.objects.bulk_create([
                    FacilityEvaluation(facility=facility, title=item['title'][:100], content=item['content'])
                    for item in eval_items if item.get('title')
                ])
            # 인력현황 항목 저장 (재생성)
            from core.models import FacilityStaff
            staff_items = data.get('staff_items') or []
            if staff_items:
                FacilityStaff.objects.filter(facility=facility).delete()
                FacilityStaff.objects.bulk_create([
                    FacilityStaff(facility=facility, title=item['title'][:100], content=item['content'])
                    for item in staff_items if item.get('title')
                ])
            # 프로그램운영 항목 저장 (재생성)
            from core.models import FacilityProgram
            program_items = data.get('program_items') or []
            if program_items:
                FacilityProgram.objects.filter(facility=facility).delete()
                FacilityProgram.objects.bulk_create([
                    FacilityProgram(facility=facility, title=item['title'][:100], content=item['content'])
                    for item in program_items if item.get('title')
                ])
            # 위치 항목 저장 (개별 항목으로 재생성)
            from core.models import FacilityLocation
            location_items = data.get('location_items') or []
            FacilityLocation.objects.filter(facility=facility).delete()
            for item in location_items:
                FacilityLocation.objects.create(facility=facility, title=item['title'], content=item['content'])
            # 홈페이지 항목 저장 (OneToOne 재생성)
            from core.models import FacilityHomepage
            homepage_item = data.get('homepage_item')
            if homepage_item:
                FacilityHomepage.objects.filter(facility=facility).delete()
                FacilityHomepage.objects.create(facility=facility, title=homepage_item['title'], content=homepage_item['content'])
            # 비급여 항목 ��장 (개별 항목으로 재생성)
            from core.models import FacilityNonCovered
            noncov_items = data.get('non_covered_items') or []
            FacilityNonCovered.objects.filter(facility=facility).delete()
            for item in noncov_items:
                FacilityNonCovered.objects.create(facility=facility, title=item['title'], content=item['content'])
        return facility
