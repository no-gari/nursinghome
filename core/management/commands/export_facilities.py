# management/commands/export_facilities.py
import csv
import json
from django.core.management.base import BaseCommand
from core.models import Facility


class Command(BaseCommand):
    help = '모든 시설 데이터를 CSV로 내보냅니다'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            type=str,
            default='facilities_export.csv',
            help='출력 파일명 (기본값: facilities_export.csv)'
        )

    def json_to_readable_string(self, json_data):
        """JSON을 읽기 쉬운 문자열로 변환"""
        if not json_data:
            return ''

        if isinstance(json_data, dict):
            # 키: 값 형태로 변환
            items = []
            for key, value in json_data.items():
                items.append(f"{key}: {value}")
            return " | ".join(items)
        else:
            return str(json_data)

    def handle(self, *args, **options):
        output_file = options['output']

        facilities = Facility.objects.all().order_by('code')
        total_count = facilities.count()

        self.stdout.write(f'총 {total_count}개 시설을 CSV로 내보냅니다...')

        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'code', 'name', 'kind', 'grade', 'availability',
                'capacity', 'occupancy', 'waiting',
                'sido', 'sigungu', 'phone', 'homepage_url', 'location_info',
                'evaluation_info', 'staff_info', 'program_info',
                'noncovered_info'
            ]

            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for facility in facilities:
                writer.writerow({
                    'code': facility.code,
                    'name': facility.name,
                    'kind': facility.kind,
                    'grade': facility.grade,
                    'availability': facility.availability,
                    'capacity': facility.capacity,
                    'occupancy': facility.occupancy,
                    'waiting': facility.waiting,
                    'sido': facility.sido,
                    'sigungu': facility.sigungu,
                    'phone': facility.phone,
                    'homepage_url': facility.homepage_url,
                    'location_info': facility.location_info,
                    'evaluation_info': self.json_to_readable_string(facility.evaluation_info),
                    'staff_info': self.json_to_readable_string(facility.staff_info),
                    'program_info': self.json_to_readable_string(facility.program_info),
                    'noncovered_info': self.json_to_readable_string(facility.noncovered_info),
                })

        self.stdout.write(
            self.style.SUCCESS(f'성공적으로 {total_count}개 시설을 {output_file}에 저장했습니다.')
        )