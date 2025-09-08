from django.shortcuts import render, get_object_or_404, redirect
from rest_framework import viewsets, status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.authentication import SessionAuthentication, BasicAuthentication  # 추가
from rest_framework.permissions import IsAuthenticated  # 추가
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.conf import settings
from .models import Facility, ChatHistory, Tag, Hospital, ChatSession, Comment
from .serializers import FacilityListSerializer, FacilityDetailSerializer, ChatRequestSerializer, ChatResponseSerializer, ChatSessionSerializer
from .rag_service import RAGService
from django.utils.decorators import method_decorator
from .regions import regions
from django.views.generic import ListView
from django.db.models import Case, When, Value, IntegerField
from django.contrib.auth.decorators import login_required
import json
from django.db.models import Avg, Count, Prefetch


@ensure_csrf_cookie
def main_view(request):
    return render(request, 'core/main.html')


@ensure_csrf_cookie
def chat_view(request):
    if not request.user.is_authenticated:
        login_url = settings.LOGIN_URL
        return redirect(f"{login_url}?next={request.path}&reason=chat")
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


class HospitalListView(ListView):
    model = Hospital
    template_name = 'core/hospital_list.html'
    context_object_name = 'hospitals'
    paginate_by = 20

    def get_queryset(self):
        queryset = Hospital.objects.all().prefetch_related('tags', 'images')
        sido = self.request.GET.get('sido', '전체')
        sigungu = self.request.GET.get('sigungu', '')
        grade = self.request.GET.get('grade', '')
        establishment = self.request.GET.get('establishment', '')
        size = self.request.GET.get('size', '')
        search = self.request.GET.get('search', '').strip()
        sort = self.request.GET.get('sort', 'grade')
        if sido and sido != '전체':
            queryset = queryset.filter(sido=sido)
            if sigungu:
                queryset = queryset.filter(sigungu=sigungu)
        if grade:
            queryset = queryset.filter(grade=grade)
        for tag_name in [establishment, size]:
            if tag_name:
                queryset = queryset.filter(tags__name__icontains=tag_name)
        if search:
            queryset = queryset.filter(name__icontains=search)
        if sort == 'grade':
            grade_order = Case(
                When(grade='1등급', then=Value(1)),
                When(grade='2등급', then=Value(2)),
                When(grade='3등급', then=Value(3)),
                When(grade='4등급', then=Value(4)),
                When(grade='5등급', then=Value(5)),
                When(grade='등급외', then=Value(6)),
                default=Value(7),
                output_field=IntegerField()
            )
            queryset = queryset.annotate(_grade_order=grade_order).order_by('_grade_order', 'name')
        else:
            queryset = queryset.order_by('name')
        return queryset.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sido = self.request.GET.get('sido', '')
        sigungu = self.request.GET.get('sigungu', '')
        grade = self.request.GET.get('grade', '')
        establishment = self.request.GET.get('establishment', '')
        size = self.request.GET.get('size', '')
        search = self.request.GET.get('search', '')
        sort = self.request.GET.get('sort', 'grade')
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
        if self.request.GET.get('ajax') == '1' or self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return render(self.request, 'core/_hospital_list_results.html', context)
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
    """RAG 챗봇 API (단발 호출)"""
    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = []  # 비로그인 허용 (저장만 제한)

    def post(self, request):
        raw_query = request.data.get('query') or request.data.get('message')
        session_id = request.data.get('session_id')
        if not raw_query:
            return Response({'error': 'query 필드가 필요합니다.'}, status=status.HTTP_400_BAD_REQUEST)

        chat_session = None
        if request.user.is_authenticated:
            if session_id:
                chat_session = ChatSession.objects.filter(id=session_id, user=request.user).first()
            if not chat_session:
                # 새 세션 생성 (첫 메시지 제목 자동)
                title = raw_query.strip()[:40]
                chat_session = ChatSession.objects.create(user=request.user, title=title)

        try:
            rag_service = RAGService()
            result = rag_service.chat(raw_query)
            answer = result.get('answer') or result.get('response') or ''
            sources = result.get('sources', [])
            cards = result.get('cards', [])  # 카드 UI 데이터 추가
            if request.user.is_authenticated:
                ChatHistory.objects.create(user=request.user, session=chat_session, query=raw_query, answer=answer, cards=cards, sources=sources)
            return Response({'answer': answer, 'sources': sources, 'cards': cards, 'session_id': chat_session.id if chat_session else None}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': f'챗봇 처리 중 오류: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ChatSessionListCreateAPI(APIView):
    """사용자 채팅 세션 목록 및 생성"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = ChatSession.objects.filter(user=request.user).order_by('-updated_at')
        data = ChatSessionSerializer(qs, many=True).data
        return Response(data)

    def post(self, request):
        title = (request.data.get('title') or '').strip()
        if not title:
            title = '새 대화'
        session = ChatSession.objects.create(user=request.user, title=title[:100])
        return Response(ChatSessionSerializer(session).data, status=status.HTTP_201_CREATED)


class ChatSessionRenameDeleteAPI(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        session = get_object_or_404(ChatSession, pk=pk, user=request.user)
        title = (request.data.get('title') or '').strip()
        if title:
            session.title = title[:255]
            session.save(update_fields=['title', 'updated_at'])
        return Response(ChatSessionSerializer(session).data)

    def delete(self, request, pk):
        session = get_object_or_404(ChatSession, pk=pk, user=request.user)
        session.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChatSessionMessagesAPI(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        session = get_object_or_404(ChatSession, pk=pk, user=request.user)
        histories = ChatHistory.objects.filter(session=session, user=request.user).order_by('created_at')
        # 프론트 기존 구조(user / bot 분리)에 맞게 변환
        messages = []
        for h in histories:
            messages.append({
                'id': f"{h.id}_q",
                'type': 'user',
                'content': h.query,
                'created_at': h.created_at,
            })
            if h.answer:
                messages.append({
                    'id': f"{h.id}_a",
                    'type': 'bot',
                    'content': h.answer,
                    'created_at': h.created_at,
                    'sources': h.sources or [],
                    'cards': h.cards or [],  # 카드 정보 추가
                })
        return Response({'session': ChatSessionSerializer(session).data, 'messages': messages})


@api_view(['POST'])
def initialize_rag(request):
    """RAG 임베딩 초기화/갱신: Facility & Hospital summary -> summary_embedding 저장.
    body 또는 query에 force=1 전달 시 기존 임베딩 재생성.
    """
    force_flag = str(request.data.get('force') or request.query_params.get('force') or '0') in ('1', 'true', 'True')
    try:
        rag_service = RAGService()
        updated = rag_service.update_all_embeddings(force=force_flag)
        return Response({
            'message': '임베딩 갱신 완료',
            'updated_facilities': updated['facility'],
            'updated_hospitals': updated['hospital'],
            'force': force_flag,
        })
    except Exception as e:
        return Response({
            'error': f'RAG 임베딩 갱신 중 오류: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def hospital_detail(request, code: str):
    hospital = get_object_or_404(Hospital, code=code)
    images = list(hospital.images.all().reverse())
    tags = list(hospital.tags.all())

    def json_items(obj):
        if not obj:
            return []
        if isinstance(obj, dict):
            return [(k, v) for k, v in obj.items()]
        return []

    bed_count_items = json_items(hospital.bed_count)

    # 병상 현황 가공 (물리치료실 / 상급 / 일반)
    import re
    def parse_int(text):
        if text is None:
            return None
        m = re.search(r"(\d+)", str(text))
        return int(m.group(1)) if m else None

    bed_counts = {}
    for k, v in bed_count_items:
        key = str(k)
        val = str(v)
        if '물리치료실' in key:
            bed_counts['therapy'] = parse_int(val)
        # 일반입원실에 상급/일반 혼합
        if ('일반입원실' in key) or ('입원실' in key and ('상급' in val or '일반' in val)):
            m_p = re.search(r"상급\s*[:：]?\s*(\d+)", val)
            m_g = re.search(r"일반\s*[:：]?\s*(\d+)", val)
            if m_p:
                bed_counts['premium'] = int(m_p.group(1))
            if m_g:
                bed_counts['general'] = int(m_g.group(1))
        else:
            if '상급' in key and 'premium' not in bed_counts:
                bed_counts['premium'] = parse_int(val)
            if '일반' in key and 'general' not in bed_counts and '상급' not in key:
                bed_counts['general'] = parse_int(val)

    # 요일 정렬 (월~일) - label이 '월요일', '월', 등으로 시작한다고 가정
    def weekday_order(label: str) -> int:
        order_prefix = ['월', '화', '수', '목', '금', '토', '일']
        for idx, p in enumerate(order_prefix):
            if str(label).startswith(p):
                return idx
        return 99  # 비요일 항목은 뒤로

    consultation_hours_items = json_items(hospital.consultation_hours)
    consultation_hours_items = sorted(consultation_hours_items, key=lambda kv: (weekday_order(kv[0]), kv[0]))

    context = {
        'hospital': hospital,
        'images': images,
        'tags': tags,
        'bed_count_items': bed_count_items,
        'bed_counts': bed_counts,
        'operation_facility_items': json_items(hospital.operation_facility),
        'doctor_count_items': json_items(hospital.doctor_count),
        'specialist_by_department_items': json_items(hospital.specialist_by_department),
        'department_specialists_items': json_items(hospital.department_specialists),
        'other_staff_items': json_items(hospital.other_staff),
        'consultation_hours_items': consultation_hours_items,
        'medical_fee_info_items': json_items(hospital.medical_fee_info),
        'google_maps_api_key': settings.GOOGLE_MAPS_API_KEY,
    }
    return render(request, 'core/hospital_detail.html', context)


def hospital_detail_by_id(request, pk: int):
    hospital = get_object_or_404(Hospital, pk=pk)
    images = list(hospital.images.all().reverse())
    tags = list(hospital.tags.all())

    def json_items(obj):
        if not obj:
            return []
        if isinstance(obj, dict):
            return [(k, v) for k, v in obj.items()]
        return []

    bed_count_items = json_items(hospital.bed_count)

    import re
    def parse_int(text):
        if text is None:
            return None
        m = re.search(r"(\d+)", str(text))
        return int(m.group(1)) if m else None

    bed_counts = {}
    for k, v in bed_count_items:
        key = str(k)
        val = str(v)
        if '물리치료실' in key:
            bed_counts['therapy'] = parse_int(val)
        if ('일반입원실' in key) or ('입원실' in key and ('상급' in val or '일반' in val)):
            m_p = re.search(r"상급\s*[:：]?\s*(\d+)", val)
            m_g = re.search(r"일반\s*[:：]?\s*(\d+)", val)
            if m_p:
                bed_counts['premium'] = int(m_p.group(1))
            if m_g:
                bed_counts['general'] = int(m_g.group(1))
        else:
            if '상급' in key and 'premium' not in bed_counts:
                bed_counts['premium'] = parse_int(val)
            if '일반' in key and 'general' not in bed_counts and '상급' not in key:
                bed_counts['general'] = parse_int(val)

    def weekday_order(label: str) -> int:
        order_prefix = ['월', '화', '수', '목', '금', '토', '일']
        for idx, p in enumerate(order_prefix):
            if str(label).startswith(p):
                return idx
        return 99

    consultation_hours_items = json_items(hospital.consultation_hours)
    consultation_hours_items = sorted(consultation_hours_items, key=lambda kv: (weekday_order(kv[0]), kv[0]))

    context = {
        'hospital': hospital,
        'images': images,
        'tags': tags,
        'bed_count_items': bed_count_items,
        'bed_counts': bed_counts,
        'operation_facility_items': json_items(hospital.operation_facility),
        'doctor_count_items': json_items(hospital.doctor_count),
        'specialist_by_department_items': json_items(hospital.specialist_by_department),
        'department_specialists_items': json_items(hospital.department_specialists),
        'other_staff_items': json_items(hospital.other_staff),
        'consultation_hours_items': consultation_hours_items,
        'medical_fee_info_items': json_items(hospital.medical_fee_info),
        'google_maps_api_key': settings.GOOGLE_MAPS_API_KEY,
    }
    return render(request, 'core/hospital_detail.html', context)


# ===== 댓글 API =====
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.views import APIView
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction

class CommentListCreateAPI(APIView):
    """GET: 대상(시설/병원) 댓글 트리 반환
    POST: 새 댓글 또는 대댓글 작성 (로그인 필요)
    query params: target_type=facility|hospital, code=<facility.code or hospital.code>
    POST body: {target_type, code, content, parent_id(optional)}
    """
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_target(self, target_type, code):
        if target_type == 'facility':
            return get_object_or_404(Facility, code=code)
        elif target_type == 'hospital':
            return get_object_or_404(Hospital, code=code)
        else:
            return None

    def build_tree(self, comments):
        # comments: queryset (ordered)
        node_map = {}
        roots = []
        for c in comments:
            node = {
                'id': c.id,
                'user': c.user.username if c.user_id else None,
                'user_first_name': getattr(c.user, 'first_name', '') if c.user_id else '',
                'rating': c.rating,
                'content': '[삭제된 댓글]' if c.is_deleted else c.content,
                'is_deleted': c.is_deleted,
                'created_at': c.created_at.isoformat(),
                'parent_id': c.parent_id,
                'replies': []
            }
            node_map[c.id] = node
        for c in comments:
            n = node_map[c.id]
            if c.parent_id and c.parent_id in node_map:
                node_map[c.parent_id]['replies'].append(n)
            else:
                roots.append(n)
        return roots

    def get(self, request):
        target_type = request.query_params.get('target_type')
        code = request.query_params.get('code')
        if not target_type or not code:
            return Response({'error': 'target_type, code 필요'}, status=400)
        target = self.get_target(target_type, code)
        if not target:
            return Response({'error': '대상 없음'}, status=404)
        if target_type == 'facility':
            qs = Comment.objects.filter(facility=target).select_related('user').order_by('created_at')
        else:
            qs = Comment.objects.filter(hospital=target).select_related('user').order_by('created_at')
        return Response({'comments': self.build_tree(qs)})

    @transaction.atomic
    def post(self, request):
        # rating upsert 지원
        if not request.user.is_authenticated:
            return Response({'error': '인증 필요'}, status=401)
        data = request.data
        target_type = data.get('target_type')
        code = data.get('code')
        content = (data.get('content') or '').strip()
        parent_id = data.get('parent_id')
        rating = data.get('rating')
        if rating is not None:
            try:
                rating = int(rating)
            except ValueError:
                return Response({'error': 'rating 형식 오류'}, status=400)
            if rating < 1 or rating > 5:
                return Response({'error': 'rating 범위 1~5'}, status=400)
        if not target_type or not code:
            return Response({'error': 'target_type, code 필수'}, status=400)
        if not parent_id and (not content):
            return Response({'error': 'content 필요'}, status=400)
        target = self.get_target(target_type, code)
        if parent_id:
            parent = Comment.objects.filter(id=parent_id).first()
            if not parent:
                return Response({'error': 'parent_id 잘못됨'}, status=400)
            if target_type == 'facility' and parent.facility_id != target.id:
                return Response({'error': '부모 댓글 대상 불일치'}, status=400)
            if target_type == 'hospital' and parent.hospital_id != target.id:
                return Response({'error': '부모 댓글 대상 불일치'}, status=400)
            if rating is not None:
                return Response({'error': '대댓글에는 rating 허용되지 않음'}, status=400)
        else:
            parent = None
        # Upsert (최상위 리뷰에서만 rating 가능)
        if parent is None and rating is not None:
            existing = Comment.objects.filter(user=request.user, parent__isnull=True,
                                              facility=target if target_type=='facility' else None,
                                              hospital=target if target_type=='hospital' else None,
                                              is_deleted=False).first()
            if existing:
                existing.content = content or existing.content
                existing.rating = rating
                existing.save(update_fields=['content','rating','updated_at'])
                return Response({'id': existing.id, 'message': 'updated'}, status=200)
        c = Comment.objects.create(
            user=request.user,
            facility=target if target_type == 'facility' else None,
            hospital=target if target_type == 'hospital' else None,
            parent=parent,
            content=content,
            rating=rating if parent is None else None
        )
        return Response({'id': c.id, 'message': 'created'}, status=201)


class ReviewSummaryAPI(APIView):
    permission_classes = []  # 공개
    def get(self, request):
        target_type = request.query_params.get('target_type')
        code = request.query_params.get('code')
        if not target_type or not code:
            return Response({'error': 'target_type, code 필요'}, status=400)
        if target_type == 'facility':
            target = get_object_or_404(Facility, code=code)
            qs = Comment.objects.filter(facility=target, parent__isnull=True, is_deleted=False, rating__isnull=False)
        else:
            target = get_object_or_404(Hospital, code=code)
            qs = Comment.objects.filter(hospital=target, parent__isnull=True, is_deleted=False, rating__isnull=False)
        agg = qs.aggregate(avg=Avg('rating'), cnt=Count('id'))
        latest_obj = qs.order_by('-created_at').first()
        latest = None
        if latest_obj:
            latest = {
                'id': latest_obj.id,
                'user_first_name': getattr(latest_obj.user, 'first_name', '') if latest_obj.user_id else '',
                'rating': latest_obj.rating,
                'content': '[삭제된 댓글]' if latest_obj.is_deleted else latest_obj.content,
                'created_at': latest_obj.created_at.isoformat(),
                'is_owner': (request.user.is_authenticated and latest_obj.user_id == request.user.id)
            }
        user_rating = None
        if request.user.is_authenticated:
            ur = qs.filter(user=request.user).first()
            if ur:
                user_rating = ur.rating
        return Response({'average': round(agg['avg'] or 0, 1), 'count': agg['cnt'], 'user_rating': user_rating, 'latest': latest})


class ReviewListAPI(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        target_type = request.query_params.get('target_type')
        code = request.query_params.get('code')
        if not target_type or not code:
            return Response({'error':'target_type, code 필요'}, status=400)
        if target_type == 'facility':
            target = get_object_or_404(Facility, code=code)
            top_qs = Comment.objects.filter(facility=target, parent__isnull=True, is_deleted=False).select_related('user').order_by('-created_at')
        else:
            target = get_object_or_404(Hospital, code=code)
            top_qs = Comment.objects.filter(hospital=target, parent__isnull=True, is_deleted=False).select_related('user').order_by('-created_at')
        replies_map = {}
        replies = Comment.objects.filter(parent_id__in=top_qs.values_list('id', flat=True)).select_related('user').order_by('created_at')
        for r in replies:
            replies_map.setdefault(r.parent_id, []).append({
                'id': r.id,
                'user_first_name': getattr(r.user, 'first_name', '') if r.user_id else '',
                'content': '[삭제된 댓글]' if r.is_deleted else r.content,
                'created_at': r.created_at.isoformat(),
                'is_owner': True if (r.user_id == request.user.id) else False,
            })
        data = []
        for c in top_qs:
            data.append({
                'id': c.id,
                'user_first_name': getattr(c.user, 'first_name', '') if c.user_id else '',
                'rating': c.rating,
                'content': '[삭제된 댓글]' if c.is_deleted else c.content,
                'created_at': c.created_at.isoformat(),
                'replies': replies_map.get(c.id, []),
                'is_owner': True if (c.user_id == request.user.id) else False,
            })
        return Response({'reviews': data})


class CommentDetailAPI(APIView):
    permission_classes = [IsAuthenticated]
    def patch(self, request, pk):
        """댓글/리뷰 수정 (본인만). 루트 댓글은 rating 수정 허용, 대댓글은 content만."""
        comment = get_object_or_404(Comment, pk=pk, user=request.user)
        if comment.is_deleted:
            return Response({'error': '삭제된 댓글'}, status=400)
        content = (request.data.get('content') or '').strip()
        rating = request.data.get('rating', None)
        updated = False
        if content:
            comment.content = content
            updated = True
        if rating is not None:
            # 대댓글은 별점 변경 불가
            if comment.parent_id is not None:
                return Response({'error': '대댓글은 별점 수정 불가'}, status=400)
            try:
                rating_int = int(rating)
            except (TypeError, ValueError):
                return Response({'error': 'rating 형식 오류'}, status=400)
            if rating_int < 1 or rating_int > 5:
                return Response({'error': 'rating 범위 1~5'}, status=400)
            comment.rating = rating_int
            updated = True
        if not updated:
            return Response({'error': '변경 내용 없음'}, status=400)
        comment.save(update_fields=['content','rating','updated_at'])
        return Response({
            'id': comment.id,
            'content': comment.content,
            'rating': comment.rating,
            'parent_id': comment.parent_id,
            'updated_at': comment.updated_at.isoformat()
        })

    def delete(self, request, pk):
        comment = get_object_or_404(Comment, pk=pk, user=request.user)
        comment.is_deleted = True
        comment.content = ''
        comment.save(update_fields=['is_deleted','content','updated_at'])
        return Response(status=204)


@ensure_csrf_cookie
def facility_review_write(request, code: str):
    if not request.user.is_authenticated:
        return redirect(f"{settings.LOGIN_URL}?next={request.path}")
    facility = get_object_or_404(Facility, code=code)
    existing = Comment.objects.filter(facility=facility, parent__isnull=True, user=request.user, is_deleted=False).first()
    error = None
    if request.method == 'POST':
        rating = request.POST.get('rating')
        content = (request.POST.get('content') or '').strip()
        try:
            rating_int = int(rating)
        except (TypeError, ValueError):
            rating_int = 0
        if rating_int < 1 or rating_int > 5:
            error = '별점(1~5)을 선택하세요.'
        elif len(content) < 5:
            error = '후기 내용을 5자 이상 작성하세요.'
        else:
            if existing:
                existing.rating = rating_int
                if content:
                    existing.content = content
                existing.save(update_fields=['rating','content','updated_at'])
                return redirect(f"/facility/{facility.code}/#reviewSummary")
            else:
                Comment.objects.create(user=request.user, facility=facility, content=content, rating=rating_int)
                return redirect(f"/facility/{facility.code}/#reviewSummary")
    context = {'target_type': 'facility', 'facility': facility, 'existing': existing, 'error': error}
    return render(request, 'core/review_form.html', context)


@ensure_csrf_cookie
def hospital_review_write(request, code: str):
    if not request.user.is_authenticated:
        return redirect(f"{settings.LOGIN_URL}?next={request.path}")
    hospital = get_object_or_404(Hospital, code=code)
    existing = Comment.objects.filter(hospital=hospital, parent__isnull=True, user=request.user, is_deleted=False).first()
    error = None
    if request.method == 'POST':
        rating = request.POST.get('rating')
        content = (request.POST.get('content') or '').strip()
        try:
            rating_int = int(rating)
        except (TypeError, ValueError):
            rating_int = 0
        if rating_int < 1 or rating_int > 5:
            error = '별점(1~5)을 선택하세요.'
        elif len(content) < 5:
            error = '후기 내용을 5자 이상 작성하세요.'
        else:
            if existing:
                existing.rating = rating_int
                if content:
                    existing.content = content
                existing.save(update_fields=['rating','content','updated_at'])
                return redirect(f"/hospital/{hospital.code}/#reviewSummary")
            else:
                Comment.objects.create(user=request.user, hospital=hospital, content=content, rating=rating_int)
                return redirect(f"/hospital/{hospital.code}/#reviewSummary")
    context = {'target_type': 'hospital', 'hospital': hospital, 'existing': existing, 'error': error}
    return render(request, 'core/review_form.html', context)
