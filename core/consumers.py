import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from core.rag_service import RAGService

logger = logging.getLogger(__name__)

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.is_streaming = False
        await self.accept()
        logger.info(f"WebSocket connected: {self.channel_name}")
        # 프론트에서 'connected' 타입을 기대할 수 있으므로 명시적 전송
        await self.send_json({'type': 'connected', 'message': '연결됨'})
        # 하위 호환 (기존 info 타입 사용하던 경우)
        await self.send_json({'type': 'info', 'message': '연결됨'})

    async def disconnect(self, close_code):
        self.is_streaming = False
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
            await self._handle_query(query)
        else:
            await self.send_json({'type': 'error', 'message': f'알 수 없는 action: {action}'})

    async def _handle_query(self, query: str):
        self.is_streaming = True
        logger.info(f"Starting query processing: {query}")

        try:
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
            self.is_streaming = False
            logger.info("Query processing finished")

    async def send_json(self, data: dict):
        try:
            await self.send(text_data=json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logger.error(f"Send error: {e}")
