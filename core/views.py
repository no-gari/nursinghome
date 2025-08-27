from django.shortcuts import render, get_object_or_404
from rest_framework import viewsets, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from .models import Facility, ChatHistory, Tag
from .serializers import FacilityListSerializer, FacilityDetailSerializer, ChatRequestSerializer, ChatResponseSerializer
from .rag_service import RAGService
from django.utils.decorators import method_decorator
from .regions import regions
from django.views.generic import ListView
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

    # OneToOne 관계 정보
    homepage_info = getattr(facility, 'homepage_info', None)
    summary_info = getattr(facility, 'summary', None)

    # 이미지 및 태그 정보
    images = list(facility.images.all())
    tags = list(facility.tags.all())

    context = {
        'facility': facility,
        'basic_items': basic_items,
        'evaluation_items': evaluation_items,
        'staff_items': staff_items,
        'program_items': program_items,
        'location_items': location_items,
        'noncovered_items': noncovered_items,
        'homepage_info': homepage_info,
        'summary_info': summary_info,
        'images': images,
        'tags': tags,
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
        current_filters = {
            'sido': sido,
            'sigungu': sigungu,
            'grade': grade,
            'establishment': establishment,
            'size': size,
            'search': search,
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
            'message': f'RAG 시스템이 초기화되었습니다. {count}개 시설이 벡터화되었습니다.',
            'facilities_count': count
        })
    except Exception as e:
        return Response({
            'error': f'RAG 초기화 중 오류가 발생했습니다: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)