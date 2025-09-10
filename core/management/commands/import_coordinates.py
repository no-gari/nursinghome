import json
from decimal import Decimal
from django.core.management.base import BaseCommand
from core.models import Facility


class Command(BaseCommand):
    help = 'JSON 파일에서 latitude, longitude 데이터를 SQLite로 가져오기'

    def add_arguments(self, parser):
        parser.add_argument('--input', type=str, default='coordinates_data.json',
                            help='입력 파일명 (기본값: coordinates_data.json)')

    def handle(self, *args, **options):
        input_file = options['input']

        try:
            with open(input_file, 'r', encoding='utf-8') as f:
                coordinates_data = json.load(f)
        except FileNotFoundError:
            self.stdout.write(
                self.style.ERROR(f'{input_file} 파일을 찾을 수 없습니다.')
            )
            return

        updated_count = 0
        not_found_count = 0

        for coord in coordinates_data:
            try:
                facility = Facility.objects.get(code=coord['code'])
                facility.latitude = Decimal(coord['latitude'])
                facility.longitude = Decimal(coord['longitude'])
                facility.save(update_fields=['latitude', 'longitude'])
                updated_count += 1
            except Facility.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(f'시설 코드 {coord["code"]}를 찾을 수 없습니다.')
                )
                not_found_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'성공적으로 {updated_count}개의 시설 좌표를 업데이트했습니다.'
            )
        )
        if not_found_count > 0:
            self.stdout.write(
                self.style.WARNING(f'{not_found_count}개의 시설을 찾을 수 없었습니다.')
            )
