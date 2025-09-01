from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.rag_service import RAGService
from core.models import Facility, Hospital


class Command(BaseCommand):
    help = "Facility / Hospital summary 필드 OpenAI 임베딩 생성/갱신 (summary_embedding 저장)."

    def add_arguments(self, parser):
        # summary 1개가 500~1000자(≈500~1000 tokens)일 수 있어 다수를 한 요청에 묶으면 토큰 한도(약 8K) 초과 위험.
        # 현재 구현은 객체별 개별 임베딩 호출이므로 batch-size는 bulk_update 용량만 의미하며 값을 낮춰 메모리/지연 위험 최소화.
        parser.add_argument('--force', action='store_true', help='기존 summary_embedding 이 있어도 재생성')
        parser.add_argument('--only', choices=['facility', 'hospital'], help='특정 모델만 갱신')
        parser.add_argument('--batch-size', type=int, default=20, help='bulk_update 배치 크기 (기본 20)')
        parser.add_argument('--limit', type=int, help='처리할 객체 수 제한(테스트용)')
        parser.add_argument('--ids', type=str, help='콤마 구분 id 리스트 (해당 id 만 처리)')

    def handle(self, *args, **options):
        force = options['force']
        only = options.get('only')
        batch_size = options['batch_size']
        limit = options.get('limit')
        ids_arg = options.get('ids')

        try:
            service = RAGService()
        except Exception as e:
            raise CommandError(f"RAGService 초기화 실패: {e}")

        def apply_filters(qs):
            if ids_arg:
                try:
                    id_list = [int(x) for x in ids_arg.split(',') if x.strip()]
                    qs = qs.filter(id__in=id_list)
                except ValueError:
                    raise CommandError('--ids 값 파싱 실패 (정수 콤마 구분)')
            if limit:
                qs = qs.order_by('id')[:limit]
            return qs

        results = {}
        if only in (None, 'facility'):
            qs = apply_filters(Facility.objects.all())
            updated = service.update_model_embeddings(qs, batch_size=batch_size, force=force)
            results['facility'] = updated
        if only in (None, 'hospital'):
            qs = apply_filters(Hospital.objects.all())
            updated = service.update_model_embeddings(qs, batch_size=batch_size, force=force)
            results['hospital'] = updated

        total = sum(results.values())
        self.stdout.write(self.style.SUCCESS(
            f"임베딩 갱신 완료 (force={force}) -> " +
            ", ".join(f"{k}:{v}" for k,v in results.items()) + f" | total={total}"))
