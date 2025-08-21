import re
from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Facility

class Command(BaseCommand):
    help = "기존 연관 모델 데이터를 새로운 JSONField 구조로 마이그레이션합니다."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='DB 저장하지 않고 결과만 출력')
        parser.add_argument('--limit', type=int, default=None, help='처리할 최대 시설 수 (디버그용)')

    def handle(self, *args, **options):
        dry = options['dry_run']
        limit = options['limit']

        qs = Facility.objects.all().order_by('id')
        if limit:
            qs = qs[:limit]

        total = qs.count()
        updated = 0
        skipped = 0

        self.stdout.write(self.style.MIGRATE_HEADING(f"대상 시설: {total} (dry_run={dry})"))

        for fac in qs.iterator():
            try:
                # 전화번호 추출
                phone = self._extract_phone(fac)

                # 홈페이지 URL 추출
                homepage_url = self._extract_homepage_url(fac)

                # 교통편 정보 추출
                location_info = self._extract_location_info(fac)

                # 평가정보 변환
                evaluation_info = self._convert_to_dict('evaluation_items', fac)

                # 인력현황 변환
                staff_info = self._convert_to_dict('staff_items', fac)

                # 프로그램운영 변환
                program_info = self._convert_to_dict('program_items', fac)

                # 비급여항목 변환 (숫자 추출)
                noncovered_info = self._convert_noncovered_to_dict(fac)

                if not dry:
                    changed = False

                    if phone and fac.phone != phone:
                        fac.phone = phone
                        changed = True

                    if homepage_url and fac.homepage_url != homepage_url:
                        fac.homepage_url = homepage_url
                        changed = True

                    if location_info and fac.location_info != location_info:
                        fac.location_info = location_info
                        changed = True

                    if evaluation_info and fac.evaluation_info != evaluation_info:
                        fac.evaluation_info = evaluation_info
                        changed = True

                    if staff_info and fac.staff_info != staff_info:
                        fac.staff_info = staff_info
                        changed = True

                    if program_info and fac.program_info != program_info:
                        fac.program_info = program_info
                        changed = True

                    if noncovered_info and fac.noncovered_info != noncovered_info:
                        fac.noncovered_info = noncovered_info
                        changed = True

                    if changed:
                        with transaction.atomic():
                            fac.save()
                        updated += 1
                        self.stdout.write(f"[업데이트] {fac.id} {fac.name}")
                    else:
                        skipped += 1
                else:
                    # dry-run 모드에서는 결과만 출력
                    self.stdout.write(f"[DRY-RUN] {fac.id} {fac.name}")
                    if phone:
                        self.stdout.write(f"  전화번호: {phone}")
                    if homepage_url:
                        self.stdout.write(f"  홈페이지: {homepage_url}")
                    if location_info:
                        self.stdout.write(f"  교통편: {location_info[:50]}...")
                    if evaluation_info:
                        self.stdout.write(f"  평가정보: {len(evaluation_info)}개")
                    if staff_info:
                        self.stdout.write(f"  인력현황: {len(staff_info)}개")
                    if program_info:
                        self.stdout.write(f"  프로그램: {len(program_info)}개")
                    if noncovered_info:
                        self.stdout.write(f"  비급여: {len(noncovered_info)}개")
                    updated += 1

            except Exception as e:
                self.stderr.write(f"[오류] {fac.id} {fac.name}: {e}")

        self.stdout.write(self.style.SUCCESS(f"업데이트: {updated}"))
        self.stdout.write(f"스킵: {skipped}")

    def _extract_phone(self, facility):
        """기본정보에서 전화번호 추출"""
        try:
            for basic in facility.basic_items.all():
                title = (basic.title or '').strip()
                if '전화' in title or '연락처' in title:
                    content = (basic.content or '').strip()
                    # 전화번호 패턴 추출 (숫자, 하이픈, 괄호만)
                    phone_match = re.search(r'[\d\-\(\)\s]+', content)
                    if phone_match:
                        phone = re.sub(r'[^\d\-]', '', phone_match.group())
                        if len(phone) >= 8:  # 최소 8자리 이상
                            return phone
        except:
            pass
        return ""

    def _extract_homepage_url(self, facility):
        """홈페이지 정보에서 URL 추출"""
        try:
            homepage_info = getattr(facility, 'homepage_info', None)
            if homepage_info:
                content = (homepage_info.content or '').strip()
                # URL 패턴 추출
                url_match = re.search(r'https?://[^\s<>"\']+', content)
                if url_match:
                    return url_match.group()
        except:
            pass
        return ""

    def _extract_location_info(self, facility):
        """위치정보에서 교통편 정보 추출"""
        try:
            for loc in facility.location_items.all():
                title = (loc.title or '').strip()
                if '교통' in title or '대중교통' in title or '버스' in title or '지하철' in title:
                    content = (loc.content or '').strip()
                    if content:
                        return content
        except:
            pass
        return ""

    def _convert_to_dict(self, related_name, facility):
        """연관 모델을 딕셔너리로 변환"""
        result = {}
        try:
            related_items = getattr(facility, related_name).all()
            for item in related_items:
                title = (item.title or '').strip()
                content = (item.content or '').strip()
                if title and content:
                    result[title] = content
        except:
            pass
        return result

    def _convert_noncovered_to_dict(self, facility):
        """비급여항목을 숫자만 추출하여 딕셔너리로 변환"""
        result = {}
        try:
            for item in facility.noncovered_items.all():
                title = (item.title or '').strip()
                content = (item.content or '').strip()
                if title and content:
                    # 숫자만 추출 (콤마 제거)
                    numbers = re.findall(r'[\d,]+', content)
                    if numbers:
                        # 가장 큰 숫자를 선택 (금액일 가능성이 높음)
                        clean_number = max(numbers, key=lambda x: len(x.replace(',', '')))
                        clean_number = clean_number.replace(',', '')
                        if clean_number.isdigit():
                            result[title] = clean_number
        except:
            pass
        return result
