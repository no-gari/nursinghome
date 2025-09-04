import json
import logging
import re
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from core.rag_service import RAGService
from django.utils import timezone
from core.models import ChatSession, ChatHistory
from django.urls import reverse

logger = logging.getLogger(__name__)

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.is_streaming = False
        self.current_session = None
        await self.accept()
        logger.info(f"WebSocket connected: {self.channel_name}")
        await self.send_json({'type': 'connected', 'message': '연결됨'})
        await self.send_json({'type': 'info', 'message': '연결됨'})

    async def disconnect(self, close_code):
        self.is_streaming = False
        self.current_session = None
        logger.info(f"WebSocket disconnected: {self.channel_name}, code: {close_code}")

    async def receive(self, text_data=None, bytes_data=None):
        logger.info(f"Received message: {text_data}")
        if text_data is None:
            return

        # 1) 우선 JSON 시도
        data = None
        if isinstance(text_data, str):
            try:
                data = json.loads(text_data)
            except json.JSONDecodeError:
                # 순수 텍스트로 들어온 경우 query 로 간주
                stripped = text_data.strip()
                if stripped:
                    data = {'action': 'chat', 'query': stripped}
        elif isinstance(text_data, (bytes, bytearray)):
            try:
                data = json.loads(text_data.decode('utf-8'))
            except Exception:
                return

        if not data:
            await self.send_json({'type': 'error', 'message': '파싱할 수 없는 메시지'})
            return

        # action 누락 시 fallback: query/message 존재하면 chat
        action = data.get('action')
        if not action:
            if 'query' in data or 'message' in data:
                action = 'chat'
                data['action'] = 'chat'
                if 'query' not in data and 'message' in data:
                    data['query'] = data['message']
        logger.info(f"Action: {action}, Data keys: {list(data.keys())}")

        if action == 'chat':
            query = data.get('query') or data.get('message') or ''
            query = str(query).strip()
            if not query:
                await self.send_json({'type': 'error', 'message': 'query 필요'})
                return
            if self.is_streaming:
                await self.send_json({'type': 'error', 'message': '이전 스트림 진행 중'})
                return
            session_id = data.get('session_id')
            await self._handle_query(query, session_id=session_id)
        else:
            await self.send_json({'type': 'error', 'message': f'알 수 없는 action: {action}'})

    async def _ensure_session(self, session_id: int, first_query: str):
        user = self.scope.get('user')
        if not user or not user.is_authenticated:
            self.current_session = None
            return None
        if session_id:
            try:
                session = await sync_to_async(ChatSession.objects.get)(id=session_id, user=user)
                self.current_session = session
                return session
            except ChatSession.DoesNotExist:
                pass
        # ��� 세션 생성
        title = first_query.strip()[:40]
        session = await sync_to_async(ChatSession.objects.create)(user=user, title=title)
        self.current_session = session
        await self.send_json({'type': 'session', 'session_id': session.id, 'title': session.title})
        return session

    async def _handle_query(self, query: str, session_id=None):
        self.is_streaming = True
        logger.info(f"Starting query processing: {query}")
        try:
            await self._ensure_session(session_id, query)
        except Exception as e:
            logger.error(f"Session ensure error: {e}")
            await self.send_json({'type': 'error', 'message': f'세션 생성 오류: {e}'})
            self.is_streaming = False
            return

        answer_buffer = []
        cards_data = []
        sources_data = []
        history_id = None

        try:
            user = self.scope.get('user')
            if user and user.is_authenticated and self.current_session:
                history = await sync_to_async(ChatHistory.objects.create)(user=user, session=self.current_session, query=query, answer='')
                history_id = history.id

            rag_service = await sync_to_async(RAGService)()
            gen = rag_service.stream_chat(query)

            def _gen_next(g):
                try:
                    return next(g)
                except StopIteration:
                    return None

            end_received = False

            async def stream_wrapper():
                nonlocal cards_data, sources_data, end_received
                try:
                    while True:
                        item = await sync_to_async(_gen_next)(gen)
                        if item is None:
                            break
                        t = item.get('type')
                        if t == 'token':
                            answer_buffer.append(item.get('text') or '')
                            await self.send_json(item)
                        elif t == 'sources':
                            cards_data = item.get('cards', [])
                            sources_data = item.get('sources', [])
                            await self.send_json(item)
                        elif t == 'end':
                            end_received = True
                            break
                except Exception as e:
                    logger.error(f"Stream error: {e}")
                    await self.send_json({'type': 'error', 'message': f'스트림 오류: {e}'})

            await stream_wrapper()

            # end 이벤트를 먼저 전송하여 LLM 답변을 완료
            if end_received:
                await self.send_json({'type': 'end'})

            # LLM 답변 완료 후 카드 추출 및 전송
            final_answer = ''.join(answer_buffer)
            logger.info(f"Final answer length: {len(final_answer)}")

            try:
                names = self._extract_entity_names(final_answer)
                logger.info(f"Extracted names: {names}")

                if names:
                    cards_data = await sync_to_async(self._build_cards_from_names)(names)
                    logger.info(f"Built {len(cards_data)} cards")

                    sources_data = [
                        {
                            'rank': c['rank'], 'type': c['type'], 'id': c['id'], 'code': c.get('code'),
                            'name': c['name'], 'distance': None, 'detail_url': c.get('detail_url'),
                            'image_urls': c.get('image_urls', []), 'has_images': c.get('has_images')
                        } for c in cards_data
                    ]

                    # LLM 답변 완료 후 카드 전송
                    await self.send_json({
                        'type': 'sources',
                        'mode': 'list',
                        'classifier_mode': 'post-parse',
                        'sources': sources_data,
                        'cards': cards_data,
                    })
                    logger.info("Sent sources event with cards after LLM completion")

            except Exception as parse_e:
                logger.error(f"카드 파싱/생성 실패: {parse_e}", exc_info=True)
        except Exception as e:
            logger.error(f"Query handling error: {e}", exc_info=True)
            await self.send_json({'type': 'error', 'message': f'처리 중 오류가 발생했습니다: {e}'})
        finally:
            # 히스토리 업데이트 (한 번만)
            try:
                user = self.scope.get('user')
                if user and user.is_authenticated and self.current_session and history_id is not None:
                    final_answer = ''.join(answer_buffer).strip()
                    await sync_to_async(ChatHistory.objects.filter(id=history_id).update)(
                        answer=final_answer,
                        cards=cards_data,
                        sources=sources_data,
                        updated_at=timezone.now()
                    )
                    self.current_session.updated_at = timezone.now()
                    await sync_to_async(self.current_session.save)(update_fields=['updated_at'])
            except Exception as save_e:
                logger.error(f"History save error: {save_e}")
            self.is_streaming = False
            logger.info("Query processing finished")

    async def send_json(self, data: dict):
        try:
            await self.send(text_data=json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logger.error(f"Send error: {e}")

    # --- 새 이름 추출 로직 --- #
    def _extract_entity_names(self, text: str):
        logger.info(f"_extract_entity_names called with text length: {len(text) if text else 0}")
        if not text:
            return []

        # 전체 텍스트를 로그로 출력 (디버깅용)
        logger.info(f"Full text content:\n{text[:1000]}...")  # 처음 1000자만

        lines = text.splitlines()
        logger.info(f"Total lines: {len(lines)}")

        names = []
        seen = set()
        stop_keywords = {'요약', '비교', '정리'}

        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue

            logger.info(f"Processing line {i}: {line}")

            # 마크다운 헤딩과 일반 번호 패턴 모두 지원
            # 패턴 1: ### 1. 이름 (마크다운 헤딩)
            # 패턴 2: 1. 이름 (일반 번호)
            m = re.match(r'^\s*#{0,3}\s*(\d{1,3})\.\s*(.+?)\s*$', line)
            if m:
                raw_name = m.group(2).strip()
                logger.info(f"Raw matched name: {raw_name}")

                # 마크다운 볼드 제거 (**텍스트** -> 텍스트)
                name = re.sub(r'\*\*(.*?)\*\*', r'\1', raw_name)
                # 다른 마크다운 제거
                name = re.sub(r'\*(.*?)\*', r'\1', name)  # *텍스트* -> 텍스트
                name = re.sub(r'`(.*?)`', r'\1', name)    # `텍스트` -> 텍스트
                # 괄호 안 설명 제거 (선택적)
                name = re.sub(r'\s*\([^)]*\)\s*$', '', name)
                name = name.strip()

                logger.info(f"Cleaned name: {name}")

                # 중단 조건 (요약/비교 섹션 시작되면 이후 무시)
                lowered = name.replace(' ', '').lower()
                if any(k in lowered for k in stop_keywords):
                    logger.info(f"Stop keyword found in: {name}")
                    break

                # 뒤에 콜론 붙은 헤더 제외
                if name.endswith(':'):
                    logger.info(f"Skipping header with colon: {name}")
                    continue

                # 너무 짧은 것 제외
                if len(name) < 2:
                    logger.info(f"Skipping too short name: {name}")
                    continue

                norm = self._normalize_name_simple(name)
                if norm in seen:
                    logger.info(f"Skipping duplicate name: {name} (normalized: {norm})")
                    continue

                seen.add(norm)
                names.append(name)
                logger.info(f"Added name: {name}")
            else:
                # 매칭되지 않는 라인도 로그
                if re.match(r'^\s*(#{0,3}\s*)?\d', line):  # 숫자로 시작하는 라인이면
                    logger.info(f"Number line but no match: {line}")

        logger.info(f"Final extracted names: {names}")
        return names[:12]  # 과도한 카드 제한

    def _normalize_name_simple(self, name: str):
        n = re.sub(r'\s+', '', name)
        suffixes = ['요양원', '노인복지센터', '복지센터', '센터', '요양병원', '병원']
        for s in suffixes:
            if n.endswith(s):
                n = n[:-len(s)]
                break
        return n.lower()

    def _build_cards_from_names(self, names):
        from core.models import Facility, Hospital
        cards = []
        # 사전으로 미리 로드 (효율)
        facilities = list(Facility.objects.filter(name__in=names).prefetch_related('images'))
        hospitals = list(Hospital.objects.filter(name__in=names).prefetch_related('images'))
        # 부분 일치 fallback 준비
        def match_name(target):
            # 정확 일치 우선
            for f in facilities:
                if f.name == target:
                    return ('facility', f)
            for h in hospitals:
                if h.name == target:
                    return ('hospital', h)
            norm_t = self._normalize_name_simple(target)
            # 부분 일치 (우선 시설)
            for f in Facility.objects.filter(name__icontains=norm_t)[:3]:
                return ('facility', f)
            for h in Hospital.objects.filter(name__icontains=norm_t)[:3]:
                return ('hospital', h)
            return (None, None)
        rank = 1
        for name in names:
            mtype, obj = match_name(name)
            if obj:
                if mtype == 'facility':
                    imgs = list(obj.images.all()[:3])
                    primary = imgs[0].image.url if imgs else None
                    immediate = None
                    if obj.capacity and obj.occupancy is not None:
                        immediate = (obj.waiting or 0) == 0 and obj.occupancy < obj.capacity
                    cards.append({
                        'rank': rank, 'type': 'facility', 'id': obj.id, 'code': obj.code, 'name': obj.name,
                        'grade': obj.grade or None, 'summary': (obj.summary or '')[:400], 'distance': None,
                        'detail_url': reverse('core:facility_detail', args=[obj.code]) if obj.code else None,
                        'image_urls': [im.image.url for im in imgs], 'primary_image_url': primary,
                        'has_images': obj.has_images, 'location': obj.location or obj.sigungu or obj.sido,
                        'capacity': obj.capacity, 'occupancy': obj.occupancy, 'waiting': obj.waiting,
                        'immediate_admission': immediate,
                    })
                else:
                    imgs = list(obj.images.all()[:3])
                    primary = imgs[0].image.url if imgs else None
                    cards.append({
                        'rank': rank, 'type': 'hospital', 'id': obj.id, 'code': obj.code, 'name': obj.name,
                        'grade': obj.grade or None, 'summary': (obj.summary or '')[:400], 'distance': None,
                        'detail_url': reverse('core:hospital_detail_by_id', args=[obj.id]),
                        'image_urls': [im.image.url for im in imgs], 'primary_image_url': primary,
                        'has_images': obj.has_images, 'location': obj.location or obj.sigungu or obj.sido,
                        'capacity': None, 'occupancy': None, 'waiting': None, 'immediate_admission': None,
                    })
            else:
                # 매칭 실패 시 placeholder (스킵하려면 continue)
                cards.append({
                    'rank': rank, 'type': 'facility', 'id': f'unknown_{rank}', 'code': None, 'name': name,
                    'grade': None, 'summary': '', 'distance': None, 'detail_url': None,
                    'image_urls': [], 'primary_image_url': None, 'has_images': False,
                    'location': None, 'capacity': None, 'occupancy': None, 'waiting': None,
                    'immediate_admission': None,
                })
            rank += 1
        return cards
