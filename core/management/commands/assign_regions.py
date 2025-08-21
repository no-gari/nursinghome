from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Facility

# 표준 행정구역 딕셔너리
REGIONS = {
    '서울특별시': ['종로구', '중구', '용산구', '성동구', '광진구', '동대문구', '중랑구', '성북구', '강북구', '도봉구', '노원구', '은평구', '서대문구', '마포구', '양천구', '강서구', '구로구', '금천구', '영등포구', '동작구', '관악구', '서초구', '강남구', '송파구', '강동구'],
    '부산광역시': ['중구', '서구', '동구', '영도구', '부산진구', '동래구', '남구', '북구', '해운대구', '사하구', '금정구', '강서구', '연제구', '수영구', '사상구', '기장군'],
    '대구광역시': ['중구', '동구', '서구', '남구', '북구', '수성구', '달서구', '달성군', '군위군'],
    '인천광역시': ['중구', '동구', '미추홀구', '연수구', '남동구', '부평구', '계양구', '서구', '강화군', '옹진군'],
    '광주광역시': ['동구', '서구', '남구', '북구', '광산구'],
    '대전광역시': ['동구', '중구', '서구', '유성구', '대덕구'],
    '울산광역시': ['중구', '남구', '동구', '북구', '울주군'],
    '세종특별자치시': ['세종특별자치시'],
    '경기도': ['수원시', '성남시', '의정부시', '안양시', '광주시', '부천시', '광명시', '평택시', '동두천시', '안산시', '고양시', '과천시', '구리시', '남양주시', '오산시', '시흥시', '군포시', '의왕시', '하남시', '용인시', '파주시', '이천시', '안성시', '김포시', '화성시', '광주시', '양주시', '포천시', '여주시', '연천군', '가평군', '양평군'],
    '강원특별자치도': ['춘천시', '원주시', '강릉시', '동해시', '태백시', '속초시', '삼척시', '홍천군', '횡성군', '영월군', '평창군', '정선군', '철원군', '화천군', '양구군', '인제군', '고성군', '양양군'],
    '충청북도': ['청주시', '충주시', '제천시', '보은군', '옥천군', '영동군', '증평군', '진천군', '괴산군', '음성군', '단양군'],
    '충청남도': ['천안시', '공주시', '보령시', '아산시', '서산시', '논산시', '계룡시', '당진시', '금산군', '부여군', '서천군', '청양군', '홍성군', '예산군', '태안군'],
    '전북특별자치도': ['전주시', '군산시', '익산시', '정읍시', '남원시', '김제시', '완주군', '진안군', '무주군', '장수군', '임실군', '순창군', '고창군', '부안군'],
    '전라남도': ['목포시', '여수시', '순천시', '나주시', '광양시', '담양군', '곡성군', '구례군', '고흥군', '보성군', '화순군', '장흥군', '강진군', '해남군', '영암군', '무안군', '함평군', '영광군', '장성군', '완도군', '진도군', '신안군'],
    '경상북도': ['포항시', '경주시', '김천시', '안동시', '구미시', '영주시', '영천시', '상주시', '문경시', '경산시', '군위군', '의성군', '청송군', '영양군', '영덕군', '청도군', '고령군', '성주군', '칠곡군', '예천군', '봉화군', '울진군', '울릉군'],
    '경상남도': ['창원시', '진주시', '통영시', '사천시', '김해시', '밀양시', '거제시', '양산시', '의령군', '함안군', '창녕군', '고성군', '남해군', '하동군', '산청군', '함양군', '거창군', '합천군'],
    '제주특별자치도': ['제주시', '서귀포시']
}

# 시도 명칭별 가능한 축약/대체 표기
SIDO_ALIASES = {
    '서울특별시': ['서울특별시', '서울시', '서울'],
    '부산광역시': ['부산광역시', '부산시', '부산'],
    '대구광역시': ['대구광역시', '대구시', '대구'],
    '인천광역시': ['인천광역시', '인천시', '인천'],
    '광주광역시': ['광주광역시', '광주시', '광주'],
    '대전광역시': ['대전광역시', '대전시', '대전'],
    '울산광역시': ['울산광역시', '울산시', '울산'],
    '세종특별자치시': ['세종특별자치시', '세종시', '세종'],
    '경기도': ['경기도', '경기'],
    '강원특별자치도': ['강원특별자치도', '강원도', '강원'],
    '충청북도': ['충청북도', '충북'],
    '충청남도': ['충청남도', '충남'],
    '전북특별자치도': ['전북특별자치도', '전라북도', '전북'],
    '전라남도': ['전라남도', '전남'],
    '경상북도': ['경상북도', '경북'],
    '경상남도': ['경상남도', '경남'],
    '제주특별자치도': ['제주특별자치도', '제주도', '제주'],
}

# 역방향 alias -> 표준 시도
ALIAS_TO_SIDO = {alias: std for std, aliases in SIDO_ALIASES.items() for alias in aliases}

class Command(BaseCommand):
    help = "Facility 주소 텍스트를 분석하여 sido / sigungu 필드를 채웁니다."

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='이미 값이 있는 시설도 다시 매핑')
        parser.add_argument('--dry-run', action='store_true', help='DB 저장하지 않고 결과만 출력')
        parser.add_argument('--limit', type=int, default=None, help='처리할 최대 시설 수 (디버그용)')

    def handle(self, *args, **options):
        force = options['force']
        dry = options['dry_run']
        limit = options['limit']

        qs = Facility.objects.all().order_by('id')
        if not force:
            qs = qs.filter(sido='')  # 미할당만
        if limit:
            qs = qs[:limit]

        total = qs.count()
        updated = 0
        skipped = 0
        unmatched = 0

        self.stdout.write(self.style.MIGRATE_HEADING(f"대상 시설: {total} (force={force}, dry_run={dry})"))

        for fac in qs.iterator():
            addr_text = self._collect_address_text(fac)
            if not addr_text:
                skipped += 1
                continue

            std_sido, sigungu = self._match_region(addr_text)

            if std_sido and sigungu:
                if not dry:
                    changed = False
                    if fac.sido != std_sido:
                        fac.sido = std_sido
                        changed = True
                    if fac.sigungu != sigungu:
                        fac.sigungu = sigungu
                        changed = True
                    if changed:
                        with transaction.atomic():
                            fac.save(update_fields=['sido', 'sigungu'])
                updated += 1
                self.stdout.write(f"[매핑] {fac.id} {fac.name} -> {std_sido} {sigungu}")
            else:
                unmatched += 1
                self.stdout.write(self.style.WARNING(f"[불일치] {fac.id} {fac.name} 주소='{addr_text[:60]}'"))

        self.stdout.write(self.style.SUCCESS(f"업데이트: {updated}"))
        self.stdout.write(self.style.WARNING(f"불일치: {unmatched}"))
        self.stdout.write(f"스킵(주소없음): {skipped}")

    def _collect_address_text(self, facility: Facility) -> str:
        """시설의 주소 정보를 수집합니다."""
        parts = []

        # location_items에서 '주소' 포함된 항목 우선
        for loc in facility.location_items.all():
            title = (loc.title or '').strip()
            if '주소' in title or title in ('주소', '위치'):  # 우선순위
                parts.append(loc.content or '')

        # 기본정보에서 '주소' 제목
        for basic in facility.basic_items.all():
            title = (basic.title or '').strip()
            if '주소' in title:
                parts.append(basic.content or '')

        # fallback: location_items 전체
        if not parts:
            parts = [l.content for l in facility.location_items.all() if l.content]

        text = ' '.join(parts).strip()
        return text

    def _match_region(self, address: str):
        """주소 텍스트에서 시도와 시군구를 매칭합니다."""
        if not address:
            return None, None

        # 1) 시도 alias 탐색 (긴 것 먼저)
        for alias in sorted(ALIAS_TO_SIDO.keys(), key=lambda x: -len(x)):
            if alias and alias in address:
                std_sido = ALIAS_TO_SIDO[alias]

                # 해당 시도의 시군구 목록 중 하나 찾기 (긴 것 먼저)
                for sg in sorted(REGIONS[std_sido], key=lambda x: -len(x)):
                    if sg in address:
                        return std_sido, sg

                # 세종 특례 (sigungu 동일)
                if std_sido == '세종특별자치시':
                    return std_sido, '세종특별자치시'

                # 시도는 찾았지만 시군구를 못 찾은 경우
                return std_sido, None

        return None, None
