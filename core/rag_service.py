import logging
from typing import Generator, Dict, Any
from django.conf import settings
from openai import OpenAI

logger = logging.getLogger(__name__)


class RAGService:
    """저장된 OpenAI Prompt (Responses API)만 호출하는 단순 서비스.

    요구사항:
      - 서버 내에서 추가 RAG 처리/분기 없음
      - 저장된 prompt id + version 그대로 사용
      - 사용자 질의는 input 으로 전달
      - 스트리밍 이벤트를 ChatConsumer 가 ���대로 중계 가능하도록 yield
    """
    LLM_MODEL = getattr(settings, 'OPENAI_LLM_MODEL', 'gpt-4o-mini')
    PROMPT_ID = getattr(settings, 'OPENAI_PROMPT_ID', '')
    PROMPT_VERSION = getattr(settings, 'OPENAI_PROMPT_VERSION', '8')

    def __init__(self):
        api_key = getattr(settings, 'OPENAI_API_KEY', None)
        if not api_key:
            raise RuntimeError('OPENAI_API_KEY 미설정')
        self.client = OpenAI(api_key=api_key)

    def chat(self, query: str) -> Dict[str, Any]:
        """단발(non-stream) 호출 (views.ChatbotAPI 호환)."""
        try:
            try:
                resp = self.client.responses.create(
                    model=self.LLM_MODEL,
                    prompt={'id': self.PROMPT_ID, 'version': self.PROMPT_VERSION},
                    input=query,
                )
            except Exception:
                # prompt 실패 시 model+input만 재시도
                resp = self.client.responses.create(
                    model=self.LLM_MODEL,
                    input=query,
                )
            # 결과 텍스트 추출 (SDK output 구조 대비)
            text_chunks = []
            output = getattr(resp, 'output', None)
            if output:
                for item in output:
                    parts = getattr(item, 'content', None) or []
                    for p in parts:
                        if getattr(p, 'type', '') == 'output_text':
                            txt = getattr(p, 'text', '')
                            if txt:
                                text_chunks.append(txt)
            else:
                # fallback: content 혹은 response_text 속성
                maybe = getattr(resp, 'response_text', None) or getattr(resp, 'content', None)
                if isinstance(maybe, str):
                    text_chunks.append(maybe)
            answer = ''.join(text_chunks).strip()
            return {'answer': answer}
        except Exception as e:
            logger.error(f"chat() 실패: {e}")
            return {'answer': f'[오류] {e}'}

    def stream_chat(self, query: str) -> Generator[Dict[str, Any], None, None]:
        """UI 가 기대하는 형식으로 스트리밍.
        순서:
          1) sources (빈 목록) 1회
          2) token 이벤트 다수
          3) end
        오류 시 token 에 오류 메시지 후 end.
        """
        # 1) 초기 sources (카드/소스 없음) - 기존 프론트 호환
        yield {
            'type': 'sources',
            'mode': 'list',
            'classifier_mode': 'direct',
            'sources': [],
            'cards': [],
        }
        # 1차: prompt + model
        try:
            try:
                with self.client.responses.stream(
                    model=self.LLM_MODEL,
                    prompt={'id': self.PROMPT_ID, 'version': self.PROMPT_VERSION},
                    input=query,
                ) as stream:
                    for event in stream:
                        et = getattr(event, 'type', None)
                        if et == 'response.output_text.delta':
                            delta = getattr(event, 'delta', '')
                            if delta:
                                yield {'type': 'token', 'text': delta}
                        elif et == 'response.error':
                            err = getattr(event, 'error', None)
                            msg = getattr(err, 'message', str(err)) if err else '알 수 없는 오류'
                            yield {'type': 'token', 'text': f'[오류] {msg}'}
                            break
            except Exception as mid_err:
                logger.warning(f"prompt 포함 스트림 실패, fallback 진행: {mid_err}")
                # 2차 fallback: model + input (prompt 제외)
                with self.client.responses.stream(
                    model=self.LLM_MODEL,
                    input=query,
                ) as stream:
                    for event in stream:
                        et = getattr(event, 'type', None)
                        if et == 'response.output_text.delta':
                            delta = getattr(event, 'delta', '')
                            if delta:
                                yield {'type': 'token', 'text': delta}
                        elif et == 'response.error':
                            err = getattr(event, 'error', None)
                            msg = getattr(err, 'message', str(err)) if err else '알 수 없는 오류'
                            yield {'type': 'token', 'text': f'[오류] {msg}'}
                            break
        except Exception as e:
            logger.error(f"Responses API 스트리밍 실패 최종: {e}")
            yield {'type': 'token', 'text': f'[오류] {e}'}
        yield {'type': 'end'}

__all__ = ['RAGService']
