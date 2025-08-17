from django.shortcuts import render, get_object_or_404
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.http import JsonResponse
from .models import Facility
from .serializers import FacilityListSerializer, FacilityDetailSerializer, ChatRequestSerializer, ChatResponseSerializer
from .rag_service import RAGService

# 기존 Django 템플릿 뷰
def chatbot_view(request):
    """Vue.js 챗봇 인터페이스"""
    return render(request, 'core/chatbot.html')

def facility_detail(request, code: str):
    facility = get_object_or_404(Facility, code=code)

    basic_items = list(facility.basic_items.all())
    evaluation_items = list(facility.evaluation_items.all())
    staff_items = list(facility.staff_items.all())
    program_items = list(facility.program_items.all())
    location_item = getattr(facility, 'location_info_simple', None)
    homepage_item = getattr(facility, 'homepage_info', None)
    noncovered_item = getattr(facility, 'noncovered_info', None)

    context = {
        'facility': facility,
        'basic_items': basic_items,
        'evaluation_items': evaluation_items,
        'staff_items': staff_items,
        'program_items': program_items,
        'location_item': location_item,
        'homepage_item': homepage_item,
        'noncovered_item': noncovered_item,
    }
    return render(request, 'core/facility_detail.html', context)

# DRF ViewSets
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

class ChatbotAPI(APIView):
    """RAG 챗봇 API"""

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        if serializer.is_valid():
            query = serializer.validated_data['query']

            try:
                rag_service = RAGService()
                result = rag_service.chat(query)

                response_serializer = ChatResponseSerializer(data=result)
                if response_serializer.is_valid():
                    return Response(response_serializer.data, status=status.HTTP_200_OK)
                else:
                    return Response(response_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            except Exception as e:
                return Response({
                    'error': f'챗봇 처리 중 오류가 발생했습니다: {str(e)}'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

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
