import json
from django.core.management.base import BaseCommand
from core.models import Facility


class Command(BaseCommand):
    help = 'PostgreSQL에서 latitude, longitude 데이터를 JSON으로 추출'

    def add_arguments(self, parser):
        parser.add_argument('--output', type=str, default='coordinates_data.json',
                            help='출력 파일명 (기본값: coordinates_data.json)')

    def handle(self, *args, **options):
        output_file = options['output']

        # latitude, longitude가 있는 시설만 추출
        facilities = Facility.objects.filter(
            latitude__isnull=False,
            longitude__isnull=False
        ).values('code', 'latitude', 'longitude')

        coordinates_data = []
        for facility in facilities:
            coordinates_data.append({
                'code': facility['code'],
                'latitude': str(facility['latitude']),  # Decimal을 문자열로 변환
                'longitude': str(facility['longitude'])
            })

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(coordinates_data, f, ensure_ascii=False, indent=2)

        self.stdout.write(
            self.style.SUCCESS(
                f'성공적으로 {len(coordinates_data)}개의 좌표 데이터를 {output_file}에 저장했습니다.'
            )
        )
