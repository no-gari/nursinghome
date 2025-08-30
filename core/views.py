from django.shortcuts import render, get_object_or_404
from rest_framework import viewsets, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.conf import settings
from .models import Facility, ChatHistory, Tag
from .serializers import FacilityListSerializer, FacilityDetailSerializer, ChatRequestSerializer, ChatResponseSerializer
from .rag_service import RAGService
from django.utils.decorators import method_decorator
from .regions import regions
from django.views.generic import ListView
from django.db.models import Case, When, Value, IntegerField
import json


@ensure_csrf_cookie
def main_view(request):
    return render(request, 'core/main.html')


@ensure_csrf_cookie
def chat_view(request):
    return render(request, 'core/chat.html')


@ensure_csrf_cookie
def chatbot_view(request):
    return render(request, 'core/main.html')


def facility_detail(request, code: str):
    facility = get_object_or_404(Facility, code=code)

    # 모든 관련 정보 수집
    basic_items = list(facility.basic_items.all())
    evaluation_items = list(facility.evaluation_items.all())
    staff_items = list(facility.staff_items.all())
    program_items = list(facility.program_items.all())
    location_items = list(facility.location_items.all())
    noncovered_items = list(facility.noncovered_items.all())

    # 프로그램 tokens 처리 (템플릿 태그 제거 대체)
    program_items_tokens = []
    for p in program_items:
        raw = p.content or ''
        # 개행, 한글쉼표 변형 통합 → 콤마 기준 분리
        normalized = raw.replace('\n', ',').replace('，', ',')
        tokens = [t.strip() for t in normalized.split(',') if t.strip()]
        program_items_tokens.append({
            'title': p.title,
            'tokens': tokens,
        })

    # 배지 키워드(존재 여부 표시 용도 필요시 유지)
    badge_keywords = ["인지프로그램", "여가프로그램", "특화프로그램"]
    flat_text = ' '.join([' '.join(pi['tokens']) for pi in program_items_tokens])
    program_badges = [kw for kw in badge_keywords if kw in flat_text]

    # OneToOne 관계 정보
    homepage_info = getattr(facility, 'homepage_info', None)
    summary_info = getattr(facility, 'summary', None)

    # 이미지 및 태그 정보
    images = list(facility.images.all().reverse())
    tags = list(facility.tags.all())

    context = {
        'facility': facility,
        'basic_items': basic_items,
        'evaluation_items': evaluation_items,
        'staff_items': staff_items,
        'program_items': program_items,  # 원본 유지
        'program_items_tokens': program_items_tokens,  # 신규
        'location_items': location_items,
        'noncovered_items': noncovered_items,
        'homepage_info': homepage_info,
        'summary_info': summary_info,
        'images': images,
        'tags': tags,
        'google_maps_api_key': settings.GOOGLE_MAPS_API_KEY,
        'program_badges': program_badges,
    }
    return render(request, 'core/facility_detail.html', context)


class FacilityListView(ListView):
    model = Facility
    template_name = 'core/facility_list.html'
    context_object_name = 'facilities'
    paginate_by = 20

    def get_queryset(self):
        queryset = Facility.objects.all().prefetch_related('tags', 'images')

        # 필터 파라미터 가져오기
        sido = self.request.GET.get('sido', '전체')
        sigungu = self.request.GET.get('sigungu', '')
        grade = self.request.GET.get('grade', '')
        establishment = self.request.GET.get('establishment', '')
        size = self.request.GET.get('size', '')
        search = self.request.GET.get('search', '').strip()
        sort = self.request.GET.get('sort', 'grade')  # 새 정렬 기준 (기본: 등급)

        # 지역 필터링
        if sido and sido != '전체':
            queryset = queryset.filter(sido=sido)
            if sigungu:
                queryset = queryset.filter(sigungu=sigungu)

        # 평가등급 필터링
        if grade:
            queryset = queryset.filter(grade=grade)

        # 태그 기반 필터링
        tag_filters = [establishment, size]
        for tag_name in tag_filters:
            if tag_name:
                queryset = queryset.filter(tags__name__icontains=tag_name)

        # 검색(시설명)
        if search:
            queryset = queryset.filter(name__icontains=search)

        # 정렬 적용
        if sort == 'grade':
            grade_order = Case(
                When(grade='A등급', then=Value(1)),
                When(grade='B등급', then=Value(2)),
                When(grade='C등급', then=Value(3)),
                When(grade='D등급', then=Value(4)),
                When(grade='E등급', then=Value(5)),
                When(grade='등급외', then=Value(6)),
                default=Value(7),
                output_field=IntegerField()
            )
            queryset = queryset.annotate(_grade_order=grade_order).order_by('_grade_order', 'name')
        else:  # 이름 오름차순
            queryset = queryset.order_by('name')

        return queryset.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # 필터 파라미터 가져오기
        sido = self.request.GET.get('sido', '')
        sigungu = self.request.GET.get('sigungu', '')
        grade = self.request.GET.get('grade', '')
        establishment = self.request.GET.get('establishment', '')
        size = self.request.GET.get('size', '')
        search = self.request.GET.get('search', '')
        sort = self.request.GET.get('sort', 'grade')  # 기본 표시도 등급 정렬
        current_filters = {
            'sido': sido,
            'sigungu': sigungu,
            'grade': grade,
            'establishment': establishment,
            'size': size,
            'search': search,
            'sort': sort,
        }
        context.update({
            'regions': regions,
            'current_filters': current_filters,
            'current_filters_json': json.dumps(current_filters, ensure_ascii=False),
            'total_count': self.get_queryset().count(),
        })
        return context

    def render_to_response(self, context, **response_kwargs):
        # AJAX(partial) 요청이면 결과 부분만 반환
        if self.request.GET.get('ajax') == '1' or self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return render(self.request, 'core/_facility_list_results.html', context)
        return super().render_to_response(context, **response_kwargs)


class FacilityViewSet(viewsets.ReadOnlyModelViewSet):
    """요양원 CRUD API"""
    queryset = Facility.objects.all()

    def get_serializer_class(self):
        if self.action == 'list':
            return FacilityListSerializer
        return FacilityDetailSerializer

    def get_queryset(self):
        queryset = Facility.objects.all()

        # 필터링 옵션
        grade = self.request.query_params.get('grade', None)
        kind = self.request.query_params.get('kind', None)
        availability = self.request.query_params.get('availability', None)

        if grade:
            queryset = queryset.filter(grade=grade)
        if kind:
            queryset = queryset.filter(kind=kind)
        if availability:
            queryset = queryset.filter(availability=availability)

        return queryset.order_by('name')


@method_decorator(csrf_exempt, name='dispatch')
class ChatbotAPI(APIView):
    """RAG 챗봇 API"""
    authentication_classes = []  # SessionAuthentication 비활성 (CSRF 회피)
    permission_classes = []

    def post(self, request):
        # 'query' 또는 'message' 둘 다 지원
        raw_query = request.data.get('query') or request.data.get('message')
        if not raw_query:
            return Response({'error': 'query 필드가 필요합니다.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            rag_service = RAGService()
            result = rag_service.chat(raw_query)
            # result 예: { 'answer': '...', 'sources': [...] }
            answer = result.get('answer') or result.get('response') or ''
            sources = result.get('sources', [])
            if request.user.is_authenticated:
                ChatHistory.objects.create(user=request.user, query=raw_query, answer=answer)
            return Response({'answer': answer, 'sources': sources}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': f'챗봇 처리 중 오류: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def initialize_rag(request):
    """RAG 시스템 초기화 (벡터 DB 구축)"""
    try:
        rag_service = RAGService()
        count = rag_service.embed_facilities()
        return Response({
            'message': f'RAG 시스템이 초기���되었습니다. {count}개 시���이 벡터화되었습니다.',
            'facilities_count': count
        })
    except Exception as e:
        return Response({
            'error': f'RAG 초기화 중 오류가 발생했습니다: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)