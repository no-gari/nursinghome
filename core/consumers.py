import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from core.rag_service import RAGService
from django.utils import timezone
from core.models import ChatSession, ChatHistory

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
        # 새 세션 생성
        title = first_query.strip()[:40]
        session = await sync_to_async(ChatSession.objects.create)(user=user, title=title)
        self.current_session = session
        await self.send_json({'type': 'session', 'session_id': session.id, 'title': session.title})
        return session

    async def _handle_query(self, query: str, session_id=None):
        self.is_streaming = True
        logger.info(f"Starting query processing: {query}")

        # 세션 확보 (인증된 사용자만)
        try:
            await self._ensure_session(session_id, query)
        except Exception as e:
            logger.error(f"Session ensure error: {e}")
            await self.send_json({'type': 'error', 'message': f'세션 생성 오류: {e}'})
            self.is_streaming = False
            return

        answer_buffer = []
        history_id = None
        try:
            user = self.scope.get('user')
            if user and user.is_authenticated and self.current_session:
                # 질문 즉시 기록 (빈 답변)
                history = await sync_to_async(ChatHistory.objects.create)(user=user, session=self.current_session, query=query, answer='')
                history_id = history.id

            logger.info("Initializing RAG service...")
            rag_service = await sync_to_async(RAGService)()
            logger.info("RAG service initialized successfully")

            gen = rag_service.stream_chat(query)

            def _gen_next(g):
                try:
                    return next(g)
                except StopIteration:
                    return None

            async def stream_wrapper():
                try:
                    while True:
                        item = await sync_to_async(_gen_next)(gen)
                        if item is None:
                            logger.info("Stream completed normally (None sentinel)")
                            break
                        if item.get('type') == 'token':
                            answer_buffer.append(item.get('text') or '')
                        logger.info(f"Stream item: {item}")
                        await self.send_json(item)
                except Exception as e:
                    logger.error(f"Stream error: {e}")
                    await self.send_json({'type': 'error', 'message': f'스트림 오류: {e}'})

            await stream_wrapper()

        except Exception as e:
            logger.error(f"Query handling error: {e}", exc_info=True)
            await self.send_json({'type': 'error', 'message': f'처리 중 오류가 발생했습니다: {e}'})
        finally:
            # 저장
            try:
                user = self.scope.get('user')
                if user and user.is_authenticated and self.current_session:
                    final_answer = ''.join(answer_buffer).strip()
                    if history_id is not None:
                        await sync_to_async(ChatHistory.objects.filter(id=history_id).update)(answer=final_answer, updated_at=timezone.now())
                    elif final_answer:
                        await sync_to_async(ChatHistory.objects.create)(user=user, session=self.current_session, query=query, answer=final_answer)
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
