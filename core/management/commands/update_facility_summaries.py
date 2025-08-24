import csv
import os
import codecs
from django.core.management.base import BaseCommand
from django.conf import settings
from core.models import Hospital


class Command(BaseCommand):
    help = 'Facility 모델의 code에 맞는 summary를 CSV에서 불러와 업데이트합니다'

    def add_arguments(self, parser):
        parser.add_argument(
            '--csv',
            default='core/management/commands/hospital_data_with_summary.csv',
            help='요약 정보가 담긴 CSV 파일의 경로'
        )
        parser.add_argument(
            '--encoding',
            default='utf-8',
            help='CSV 파일의 인코딩 (예: utf-8, cp949, euc-kr)'
        )

    def handle(self, *args, **options):
        csv_path = options['csv']
        encoding = options['encoding']

        if not os.path.exists(csv_path):
            self.stdout.write(self.style.ERROR(f'CSV 파일이 존재하지 않습니다: {csv_path}'))
            return

        # CSV 파일 읽기
        updated_count = 0
        skipped_count = 0
        not_found_count = 0

        try:
            with open(csv_path, 'r', encoding=encoding) as csvfile:
                reader = csv.DictReader(csvfile)

                # 각 행에 대해 처리
                for row in reader:
                    code = row.get('code')
                    summary = row.get('summary')

                    if not code or not summary:
                        skipped_count += 1
                        continue

                    try:
                        # 해당 코드를 가진 Facility 찾기
                        facility = Hospital.objects.get(code=code)

                        # summary 업데이트
                        facility.summary = summary
                        facility.save(update_fields=['summary'])

                        updated_count += 1
                        self.stdout.write(f'시설 "{facility.name}" (코드: {code})의 요약이 업데이트되었습니다.')

                    except Hospital.DoesNotExist:
                        not_found_count += 1
                        self.stdout.write(self.style.WARNING(f'코드 {code}에 해당하는 시설을 찾을 수 없습니다.'))
        except UnicodeDecodeError:
            # UTF-8로 실패했을 경우 다른 인코딩 시도
            if encoding == 'utf-8':
                self.stdout.write(self.style.WARNING(f'UTF-8 인코딩으로 파일을 읽을 수 없습니다. CP949로 시도합니다.'))
                options['encoding'] = 'cp949'
                return self.handle(*args, **options)
            else:
                self.stdout.write(self.style.ERROR(f'{encoding} 인코딩으로 파일을 읽을 수 없습니다. 올바른 인코딩을 지정해주세요.'))
                return

        # 최종 결과 출력
        self.stdout.write(self.style.SUCCESS(
            f'완료: {updated_count}개 시설 요약 업데이트됨, {skipped_count}개 항목 건너뜀, {not_found_count}개 시설 코드 없음'
        ))
