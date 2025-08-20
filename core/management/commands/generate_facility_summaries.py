import requests
import json
import time
import random
from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Facility, FacilitySummary
from tqdm import tqdm

class Command(BaseCommand):
    help = "Facility의 모든 정보를 Ollama API로 요약하여 FacilitySummary에 저장"

    def add_arguments(self, parser):
        parser.add_argument("--facility-code", help="특정 시설 코드만 요약")
        parser.add_argument("--limit", type=int, default=None, help="요약할 시설 수 제한")
        parser.add_argument("--model", default="llama3.2", help="사용할 Ollama 모델 (기본: llama3.2)")
        parser.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama API URL")
        parser.add_argument("--delay", type=float, default=1.0, help="요청 간 지연시간(초)")
        parser.add_argument("--force", action="store_true", help="이미 요약이 있어도 다시 생성")

    def handle(self, *args, **options):
        facility_code = options.get('facility_code')
        limit = options.get('limit')
        model_name = options.get('model')
        ollama_url = options.get('ollama_url')
        delay = options.get('delay')
        force_regenerate = options.get('force')

        # 요약할 시설 선택
        if facility_code:
            facilities = Facility.objects.filter(code=facility_code)
            if not facilities.exists():
                self.stdout.write(self.style.ERROR(f"시설 코드 {facility_code}를 찾을 수 없습니다."))
                return
        else:
            facilities = Facility.objects.all()
            if limit:
                facilities = facilities[:limit]

        # 이미 요약이 있는 시설 제외 (force 옵션이 없을 때)
        if not force_regenerate:
            facilities = facilities.exclude(summary__is_generated=True)

        self.stdout.write(f"총 {facilities.count()}개 시설 요약 생성 시작")
        self.stdout.write(f"사용 모델: {model_name}")
        self.stdout.write(f"Ollama URL: {ollama_url}")

        # Ollama 연결 테스트
        if not self.test_ollama_connection(ollama_url):
            self.stdout.write(self.style.ERROR("Ollama 서버에 연결할 수 없습니다."))
            return

        success_count = 0
        error_count = 0

        for facility in tqdm(facilities, desc="시설 요약"):
            try:
                self.generate_facility_summary(facility, model_name, ollama_url)
                success_count += 1
                self.stdout.write(f"[성공] {facility.code} - {facility.name}")
            except Exception as e:
                error_count += 1
                self.stderr.write(f"[오류] {facility.code}: {e}")

            # 지연
            time.sleep(delay + random.uniform(0, delay/2))

        self.stdout.write(f"\n요약 생성 완료: 성공 {success_count}, 실패 {error_count}")

    def test_ollama_connection(self, ollama_url):
        """Ollama 서버 연결 테스트"""
        try:
            response = requests.get(f"{ollama_url}/api/tags", timeout=10)
            return response.status_code == 200
        except Exception:
            return False

    def generate_facility_summary(self, facility, model_name, ollama_url):
        """개별 시설의 요약 생성"""

        # 시설의 모든 정보 수집
        facility_data = self.collect_facility_data(facility)

        # 프롬프트 생성
        prompt = self.create_summary_prompt(facility_data)

        # Ollama API 요청
        summary_text = self.call_ollama_api(prompt, model_name, ollama_url)

        # FacilitySummary 저장
        summary, created = FacilitySummary.objects.get_or_create(
            facility=facility,
            defaults={
                'content': summary_text,
                'model_name': model_name,
                'is_generated': True
            }
        )

        if not created:
            # 이미 존재하면 업데이트
            summary.content = summary_text
            summary.model_name = model_name
            summary.is_generated = True
            summary.save()

    def collect_facility_data(self, facility):
        """시설의 모든 정보를 수집"""
        data = {
            'basic_info': {
                'name': facility.name,
                'code': facility.code,
                'kind': facility.kind,
                'grade': facility.grade,
                'availability': facility.availability,
                'capacity': facility.capacity,
                'occupancy': facility.occupancy,
                'waiting': facility.waiting,
            },
            'basic_items': [],
            'evaluation_items': [],
            'staff_items': [],
            'program_items': [],
            'location_items': [],
            'noncovered_items': [],
            'homepage_info': None,
            'tags': []
        }

        # 기본정보
        for item in facility.basic_items.all():
            data['basic_items'].append({
                'title': item.title,
                'content': item.content
            })

        # 평가정보
        for item in facility.evaluation_items.all():
            data['evaluation_items'].append({
                'title': item.title,
                'content': item.content
            })

        # 인력현황
        for item in facility.staff_items.all():
            data['staff_items'].append({
                'title': item.title,
                'content': item.content
            })

        # 프로그램운영
        for item in facility.program_items.all():
            data['program_items'].append({
                'title': item.title,
                'content': item.content
            })

        # 위치정보
        for item in facility.location_items.all():
            data['location_items'].append({
                'title': item.title,
                'content': item.content
            })

        # 비급여 항목
        for item in facility.noncovered_items.all():
            data['noncovered_items'].append({
                'title': item.title,
                'content': item.content
            })

        # 홈페이지 정보
        if hasattr(facility, 'homepage_info'):
            data['homepage_info'] = {
                'title': facility.homepage_info.title,
                'content': facility.homepage_info.content
            }

        # 태그 정보
        for tag in facility.tags.all():
            data['tags'].append(tag.name)

        return data

    def create_summary_prompt(self, facility_data):
        """요약 생성을 위한 프롬프트 생성"""

        basic_info = facility_data['basic_info']

        prompt = f"""다음은 '{basic_info['name']}'라는 요양시설의 상세 정보입니다. 이 정보를 바탕으로 종합적이고 유용한 요약을 한국어로 작성해주세요.

## 기본 정보
- 시설명: {basic_info['name']}
- 유형: {basic_info['kind']}
- 평가등급: {basic_info['grade']}
- 이용가능성: {basic_info['availability']}
- 정원: {basic_info['capacity']}명
- 현원: {basic_info['occupancy']}명
- 대기: {basic_info['waiting']}명

"""

        # 태그 정보
        if facility_data['tags']:
            prompt += f"## 시설 특징\n- {', '.join(facility_data['tags'])}\n\n"

        # 각 섹션별 정보 추가
        sections = [
            ('기본정보', facility_data['basic_items']),
            ('평가정보', facility_data['evaluation_items']),
            ('인력현황', facility_data['staff_items']),
            ('프로그램운영', facility_data['program_items']),
            ('위치정보', facility_data['location_items']),
            ('비급여항목', facility_data['noncovered_items'])
        ]

        for section_name, items in sections:
            if items:
                prompt += f"## {section_name}\n"
                for item in items:
                    if item['content'].strip():
                        prompt += f"### {item['title']}\n{item['content']}\n\n"

        # 홈페이지 정보
        if facility_data['homepage_info'] and facility_data['homepage_info']['content']:
            prompt += f"## 홈페이지 정보\n{facility_data['homepage_info']['content']}\n\n"

        prompt += """
위 정보를 바탕으로 다음 사항들을 포함한 종합적인 요약을 500-800자 정도로 작성해주세요:

1. 시설의 주요 특징과 강점
2. 제공하는 주요 서비스와 프로그램
3. 시설 규모와 현황
4. 평가 등급과 주요 평가 내용
5. 입소를 고려할 때 참고할 만한 정보

요약은 요양시설을 찾는 가족들이 쉽게 이해할 수 있도록 친근하고 명확하게 작성해주세요."""

        return prompt

    def call_ollama_api(self, prompt, model_name, ollama_url):
        """Ollama API 호출"""

        url = f"{ollama_url}/api/generate"

        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": False
        }

        try:
            response = requests.post(
                url,
                json=payload,
                timeout=120  # 2분 타임아웃
            )
            response.raise_for_status()

            result = response.json()
            return result.get('response', '요약 생성 실패')

        except requests.exceptions.RequestException as e:
            raise Exception(f"Ollama API 요청 실패: {e}")
        except json.JSONDecodeError as e:
            raise Exception(f"Ollama API 응답 파싱 실패: {e}")
