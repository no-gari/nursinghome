from django.shortcuts import render, get_object_or_404
from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.core.paginator import Paginator
from django.db.models import Q
from .models import Facility, ChatHistory, Tag
from .serializers import FacilityListSerializer, FacilityDetailSerializer, ChatRequestSerializer, ChatResponseSerializer
from .rag_service import RAGService
from django.utils.decorators import method_decorator

@ensure_csrf_cookie
def main_view(request):
    """메인 페이지"""
    return render(request, 'core/main.html')

@ensure_csrf_cookie
def chat_view(request):
    """채팅 페이지"""
    return render(request, 'core/chat.html')

@ensure_csrf_cookie
# 기존 Django 템플릿 뷰 (호환성을 위해 유지)
def chatbot_view(request):
    """Vue.js 챗봇 인터페이스 (CSRF 쿠키 강제 세팅)"""
    # 메인 페이지로 리디렉션
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

@ensure_csrf_cookie
def facility_list_view(request):
    """시설 리스트 페이지 (필터링 지원)"""

    # 필터 파라미터 가져오기
    sido = request.GET.get('sido', '')
    sigungu = request.GET.get('sigungu', '')
    grade = request.GET.get('grade', '')
    size = request.GET.get('size', '')
    establishment = request.GET.get('establishment', '')
    care_partner = request.GET.get('care_partner', '')
    special_facility = request.GET.getlist('special_facility')
    programs = request.GET.getlist('programs')
    search = request.GET.get('search', '')

    # 기본 쿼리셋
    facilities = Facility.objects.all()

    # 검색어 필터링
    if search:
        facilities = facilities.filter(
            Q(name__icontains=search) |
            Q(code__icontains=search)
        )

    # 지역 필터링 (기본정보에서 주소 정보 활용)
    if sido or sigungu:
        location_query = Q()
        if sido:
            location_query &= Q(basic_items__content__icontains=sido)
        if sigungu:
            location_query &= Q(basic_items__content__icontains=sigungu)
        facilities = facilities.filter(location_query)

    # 평가등급 필터링
    if grade:
        grade_map = {
            'A등급': 'A', 'B등급': 'B', 'C등급': 'C',
            'D등급': 'D', 'E등급': 'E', '등급외': '등급외'
        }
        if grade in grade_map:
            facilities = facilities.filter(grade__icontains=grade_map[grade])

    # 태그 기반 필터링
    tag_filters = []

    # 시설규모 필터링
    if size:
        tag_filters.append(size)

    # 설립년도 필터링
    if establishment:
        establishment_map = {
            '신규시설': '신규',
            '5년이내': '5년',
            '10년이내': '10년',
            '10년이상': '10년이상'
        }
        if establishment in establishment_map:
            tag_filters.append(establishment_map[establishment])

    # 돌봄파트너 필터링
    if care_partner == 'Y':
        tag_filters.append('돌봄파트너')

    # 특수시설 필터링
    for special in special_facility:
        if special == 'premium_room':
            tag_filters.append('상급침실')
        elif special == 'dementia_care':
            tag_filters.append('치매전담실')

    # 프로그램 필터링
    program_map = {
        'exercise_support': '운동보조',
        'exercise_therapy': '운동요법',
        'music_activity': '음악활동',
        'cognitive_stimulation': '인지자극활동',
        'cognitive_improvement': '인지기능향상',
        'reality_orientation': '현실인식훈련',
        'family_participation': '가족참여',
        'other': '기타'
    }
    for program in programs:
        if program in program_map:
            tag_filters.append(program_map[program])

    # 태그 필터 적용
    if tag_filters:
        for tag_name in tag_filters:
            facilities = facilities.filter(tags__name__icontains=tag_name)

    # 중복 제거
    facilities = facilities.distinct()

    # 페이지네이션
    page = request.GET.get('page', 1)
    paginator = Paginator(facilities, 20)  # 페이지당 20개
    facilities_page = paginator.get_page(page)

    # 지역 데이터
    regions = {
        '서울특별시': ['종로구', '중구', '용산구', '성동구', '광진구', '동대문구', '중랑구', '성북구', '강북구', '도봉구', '노원구', '은평구', '서대문구', '마포구', '양천구', '강서구', '구로구', '금천구', '영등포구', '동작구', '관악구', '서초구', '강남구', '송파구', '강동구'],
        '부산광역시': ['중구', '서구', '동구', '영도구', '부산진구', '동래구', '남구', '북구', '해운대구', '사하구', '금정구', '강서구', '연제구', '수영구', '사상구', '기장군'],
        '대구광역시': ['중구', '동구', '서구', '남구', '북구', '수성구', '달서구', '달성군'],
        '인천광역시': ['중구', '동구', '미추홀구', '연수구', '남동구', '부평구', '계양구', '서구', '강화군', '옹진군'],
        '광주광역시': ['동구', '서구', '남구', '북구', '광산구'],
        '대전광역시': ['동구', '중구', '서구', '유성구', '대덕구'],
        '울산광역시': ['중구', '남구', '동구', '북구', '울주군'],
        '세종특별자치시': ['세종특별자치시'],
        '경기도': ['수원시', '성남시', '의정부시', '안양시', '부천시', '광명시', '평택시', '동두천시', '안산시', '고양시', '과천시', '구리시', '남양주시', '오산시', '시흥시', '군포시', '의왕시', '하남시', '용인시', '파주시', '이천시', '안성시', '김포시', '화성시', '광주시', '양주시', '포천시', '여주시', '연천군', '가평군', '양평군'],
        '강원특별자치도': ['춘천시', '원주시', '강릉시', '동해시', '태백시', '속초시', '삼척시', '홍천군', '횡성군', '영월군', '평창군', '정선군', '철원군', '화천군', '양구군', '인제군', '고성군', '양양군'],
        '충청북도': ['청주시', '충주시', '제천시', '보은군', '옥천군', '영동군', '증평군', '진천군', '괴산군', '음성군', '단양군'],
        '충청남도': ['천안시', '공주시', '보령시', '아산시', '서산시', '논산시', '계룡시', '당진시', '금산군', '부여군', '서천군', '청양군', '홍성군', '예산군', '태안군'],
        '전북특별자치도': ['전주시', '군산시', '익산시', '정읍시', '남원시', '김제시', '완주군', '진안군', '무주군', '장수군', '임실군', '순창군', '고창군', '부안군'],
        '전라남도': ['목포시', '여수시', '순천시', '나주시', '광양시', '담양군', '곡성군', '구례군', '고흥군', '보성군', '화순군', '장흥군', '강진군', '해남군', '영암군', '무안군', '함평군', '영광군', '장성군', '완도군', '진도군', '신안군'],
        '경상북도': ['포항시', '경주시', '김천시', '안동시', '구미시', '영주시', '영천시', '상주시', '문경시', '경산시', '군위군', '의성군', '청송군', '영양군', '영덕군', '청도군', '고령군', '성주군', '칠곡군', '예천군', '봉화군', '울진군', '울릉군'],
        '경상남도': ['창원시', '진주시', '통영시', '사천시', '김해시', '밀양시', '거제시', '양산시', '의령군', '함안군', '창녕군', '고성군', '남해군', '하동군', '산청군', '함양군', '거창군', '합천군'],
        '제주특별자치도': ['제주시', '서귀포시']
    }

    context = {
        'facilities': facilities_page,
        'regions': regions,
        'current_filters': {
            'sido': sido,
            'sigungu': sigungu,
            'grade': grade,
            'size': size,
            'establishment': establishment,
            'care_partner': care_partner,
            'special_facility': special_facility,
            'programs': programs,
            'search': search,
        },
        'total_count': facilities.count(),
    }

    return render(request, 'core/facility_list.html', context)

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
