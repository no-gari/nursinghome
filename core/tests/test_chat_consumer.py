import pytest
from channels.testing import WebsocketCommunicator
from config.asgi import application
from unittest.mock import patch

class DummyRAG:
    def stream_chat(self, query, top_k=5):
        def gen():
            yield {'type': 'sources', 'sources': []}
            yield {'type': 'token', 'text': 'hi'}
            yield {'type': 'end'}
        return gen()

@pytest.mark.asyncio
async def test_chat_consumer_stream():
    with patch('core.consumers.RAGService', DummyRAG):
        communicator = WebsocketCommunicator(application, '/ws/chat/')
        connected, _ = await communicator.connect()
        assert connected
        await communicator.send_json_to({'action': 'chat', 'query': 'hello'})
        assert await communicator.receive_json_from() == {'type': 'sources', 'sources': []}
        assert await communicator.receive_json_from() == {'type': 'token', 'text': 'hi'}
        assert await communicator.receive_json_from() == {'type': 'end'}
        await communicator.disconnect()
