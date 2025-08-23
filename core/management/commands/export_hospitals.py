import csv
from django.core.management.base import BaseCommand
from core.models import Hospital


class Command(BaseCommand):
    help = 'Hospital 데이터를 CSV 파일로 내보냅니다'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output',
            default='hospitals.csv',
            help='출력할 CSV 파일명 (기본: hospitals.csv)'
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='내보낼 병원 수 제한'
        )
        parser.add_argument(
            '--sido',
            help='특정 시도만 내보내기'
        )
        parser.add_argument(
            '--has-images',
            action='store_true',
            help='이미지가 있는 병원만 내보내기'
        )

    def handle(self, *args, **options):
        output_file = options['output']
        limit = options.get('limit')
        sido = options.get('sido')
        has_images = options.get('has_images')

        # 쿼리셋 구성
        hospitals = Hospital.objects.all().order_by('name')

        if sido:
            hospitals = hospitals.filter(sido=sido)

        if has_images:
            hospitals = hospitals.filter(has_images=True)

        if limit:
            hospitals = hospitals[:limit]

        # CSV 파일 생성
        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'code', 'name', 'grade', 'establishment_type', 'phone', 'establishment_date',
                'bed_count', 'operation_facility', 'doctor_count', 'specialist_by_department',
                'department_specialists', 'other_staff', 'consultation_hours', 'location',
                'has_images', 'sido', 'sigungu', 'summary'
            ]

            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            exported_count = 0

            for hospital in hospitals:
                # JSON 필드를 문자열로 변환
                bed_count_str = self.format_json_field(hospital.bed_count)
                operation_facility_str = self.format_json_field(hospital.operation_facility)
                doctor_count_str = self.format_json_field(hospital.doctor_count)
                specialist_by_department_str = self.format_json_field(hospital.specialist_by_department)
                department_specialists_str = self.format_json_field(hospital.department_specialists)
                other_staff_str = self.format_json_field(hospital.other_staff)
                consultation_hours_str = self.format_json_field(hospital.consultation_hours)

                writer.writerow({
                    'code': hospital.code,
                    'name': hospital.name,
                    'grade': hospital.grade,
                    'establishment_type': hospital.establishment_type,
                    'phone': hospital.phone,
                    'establishment_date': hospital.establishment_date.strftime('%Y-%m-%d') if hospital.establishment_date else '',
                    'bed_count': bed_count_str,
                    'operation_facility': operation_facility_str,
                    'doctor_count': doctor_count_str,
                    'specialist_by_department': specialist_by_department_str,
                    'department_specialists': department_specialists_str,
                    'other_staff': other_staff_str,
                    'consultation_hours': consultation_hours_str,
                    'location': hospital.location,
                    'has_images': hospital.has_images,
                    'sido': hospital.sido,
                    'sigungu': hospital.sigungu,
                    'summary': hospital.summary
                })

                exported_count += 1

        self.stdout.write(
            self.style.SUCCESS(f'{exported_count}개 병원 데이터를 {output_file}에 저장했습니다.')
        )

    def format_json_field(self, json_data):
        """JSON 필드를 CSV에 적합한 문자열로 변환"""
        if not json_data:
            return ''

        items = []
        for key, value in json_data.items():
            if value:
                items.append(f"{key}: {value}")

        return ' | '.join(items)
