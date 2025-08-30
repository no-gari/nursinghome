import re
from typing import List
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Facility, FacilityLocation


class Command(BaseCommand):
    help = "FacilityLocation 레코드에서 주소(제목: 주소/위치)를 추출해 Facility.location 필드를 채웁니다."

    def add_arguments(self, parser):
        parser.add_argument('--overwrite', action='store_true', help='이미 location 값이 있는 시설도 덮어쓰기')
        parser.add_argument('--limit', type=int, default=None, help='처리할 Facility 최대 개수')
        parser.add_argument('--batch-size', type=int, default=500, help='bulk_update 배치 크기')
        parser.add_argument('--dry-run', action='store_true', help='DB 저장 없이 시뮬레이션만 수행')

    def handle(self, *args, **options):
        overwrite = options['overwrite']
        limit = options['limit']
        batch_size = options['batch_size']
        dry_run = options['dry_run']

        qs = Facility.objects.all()
        if not overwrite:
            qs = qs.filter(location__exact='')  # CharField blank 조건
        if limit:
            qs = qs.order_by('id')[:limit]

        facilities_to_update: List[Facility] = []
        processed = success = skipped = 0

        for facility in qs.iterator(chunk_size=1000):
            processed += 1
            addr = self._extract_address(facility)
            if not addr:
                skipped += 1
                continue
            facility.location = addr
            facilities_to_update.append(facility)
            success += 1

            if len(facilities_to_update) >= batch_size:
                self._flush(facilities_to_update, dry_run)

        # flush 잔여
        self._flush(facilities_to_update, dry_run)

        self.stdout.write(self.style.SUCCESS(
            f"완료: 처리 {processed}, 성공 {success}, 스킵 {skipped}, 저장 {0 if dry_run else success}"))
        if dry_run:
            self.stdout.write(self.style.WARNING('dry-run: 실제 DB 변경 없음'))

    # ---------------- internal helpers ----------------
    def _extract_address(self, facility: Facility):
        # 우선순위: 제목이 '주소' -> '위치' -> 첫 FacilityLocation
        loc_qs = FacilityLocation.objects.filter(facility=facility)
        for title in ('주소', '위치'):
            obj = loc_qs.filter(title__icontains=title).order_by('id').first()
            if obj and obj.content:
                addr = self._clean(obj.content)
                if addr:
                    return addr
        # fallback
        obj = loc_qs.order_by('id').first()
        if obj and obj.content:
            return self._clean(obj.content)
        return None

    _MULTI_SPACE = re.compile(r'\s+')

    def _clean(self, text: str) -> str:
        t = text.strip()
        # 라인 브레이크/다중 공백 -> 단일 공백
        t = self._MULTI_SPACE.sub(' ', t.replace('\r', ' ').replace('\n', ' '))
        # 주소 끝에 붙은 불필요한 마침표/쉼표 제거
        t = t.rstrip(' ,.;')
        # 너무 짧으면 무시
        if len(t) < 5:
            return ''
        return t

    def _flush(self, facilities: List[Facility], dry_run: bool):
        if not facilities:
            return
        if dry_run:
            facilities.clear()
            return
        with transaction.atomic():
            Facility.objects.bulk_update(facilities, ['location', 'updated_at'])
        facilities.clear()

