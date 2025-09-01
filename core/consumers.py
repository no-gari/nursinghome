import json

from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .models import ChatSession, ChatMessage
from .rag_service import RAGService


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        session_id = self.scope["url_route"]["kwargs"].get("session_id")

        if not user or not user.is_authenticated or not session_id:
            await self.close()
            return

        try:
            self.session = await database_sync_to_async(
                ChatSession.objects.get
            )(pk=session_id, user=user)
        except ChatSession.DoesNotExist:
            await self.close()
            return

        await self.accept()

    async def receive(self, text_data=None, bytes_data=None):
        data = json.loads(text_data or "{}")
        message = data.get("message")
        if not message:
            return

        await database_sync_to_async(ChatMessage.objects.create)(
            session=self.session, role="user", content=message
        )

        rag_service = RAGService()
        result = await sync_to_async(rag_service.chat)(message)
        answer = result.get("answer", "")

        await database_sync_to_async(ChatMessage.objects.create)(
            session=self.session, role="assistant", content=answer
        )

        await self.send(text_data=json.dumps({"answer": answer}))

