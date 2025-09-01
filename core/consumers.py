import json
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from core.rag_service import RAGService


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.is_streaming = False
        await self.accept()
        await self.send_json({'type': 'info', 'message': '연결됨'})

    async def disconnect(self, close_code):
        self.is_streaming = False

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send_json({'type': 'error', 'message': '잘못된 JSON'})
            return
        action = data.get('action')
        if action == 'chat':
            query = data.get('query', '').strip()
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
        try:
            rag_service = await sync_to_async(RAGService)()
        except Exception as e:
            await self.send_json({'type': 'error', 'message': f'RAG 초기화 실패: {e}'})
            self.is_streaming = False
            return
        # 동기 제너레이터 획득
        gen = rag_service.stream_chat(query)
        while True:
            try:
                item = await sync_to_async(next)(gen)
            except StopIteration:
                break
            except Exception as e:
                await self.send_json({'type': 'error', 'message': f'스트림 오류: {e}'})
                break
            else:
                await self.send_json(item)
        self.is_streaming = False

    async def send_json(self, data: dict):
        await self.send(text_data=json.dumps(data, ensure_ascii=False))
