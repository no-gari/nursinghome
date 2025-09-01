import re
from typing import List, Dict, Any, Sequence  # Sequence 미사용 가능하지만 유지

from django.conf import settings
from django.db import connection
from django.db.models import QuerySet

import numpy as np

from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage

from core.models import Facility, Hospital


class RAGService:
    """LangChain + OpenAI 임베딩 + pgvector(summary_embedding) 기반 RAG 서비스.

    변경: summary 전체를 그대로 단일 임베딩 (문장 분할/평균 제거).
    흐름:
      1) Facility / Hospital.summary 전체 문자열을 임베딩
      2) summary_embedding 필드에 그대로 저장
      3) 질의 시 query 임베딩과 summary_embedding cosine 거리 검색
      4) ChatOpenAI 답변 생성
    """

    EMBEDDING_MODEL = getattr(settings, 'OPENAI_EMBEDDING_MODEL', 'text-embedding-3-small')
    LLM_MODEL = getattr(settings, 'OPENAI_LLM_MODEL', 'gpt-4o')

    def __init__(self):
        api_key = getattr(settings, 'OPENAI_API_KEY', None)
        if not api_key:
            raise RuntimeError('OPENAI_API_KEY 가 settings 에 설정되어 있어야 합니다.')
        # LangChain OpenAI Embeddings & LLM
        self.embeddings = OpenAIEmbeddings(model=self.EMBEDDING_MODEL, api_key=api_key)
        self.llm = ChatOpenAI(model=self.LLM_MODEL, temperature=0.3, api_key=api_key)

    # ------------------------- Text / Sentence Utilities ------------------------- #
    sentence_pattern = re.compile(r'([^.!?\n]+[.!?])', re.UNICODE)

    @classmethod
    def split_sentences(cls, text: str) -> List[str]:
        """(이전 단계 호환용, 현재는 사용하지 않음)"""
        if not text:
            return []
        normalized = re.sub(r'\s+', ' ', text).strip()
        if not normalized:
            return []
        return [normalized]

    # ------------------------- Search (pgvector cosine) ------------------------- #
    def _pgvector_supported(self) -> bool:
        # 간단 체크: summary_embedding 컬럼이 vector 타입인 경우 (PostgreSQL 필요)
        with connection.cursor() as cur:
            try:
                cur.execute("SELECT 1 FROM pg_type WHERE typname = 'vector'")
                return bool(cur.fetchone())
            except Exception:
                return False

    def _search_postgres(self, query_embedding: List[float], top_k: int) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        # Facility
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, summary, (summary_embedding <=> %s) AS distance
                FROM core_facility
                WHERE summary_embedding IS NOT NULL
                ORDER BY summary_embedding <=> %s
                LIMIT %s
                """,
                [query_embedding, query_embedding, top_k]
            )
            for row in cur.fetchall():
                results.append({
                    'type': 'facility',
                    'id': row[0],
                    'name': row[1],
                    'summary': row[2] or '',
                    'distance': float(row[3]) if row[3] is not None else 0.0,
                })
        # Hospital
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, summary, (summary_embedding <=> %s) AS distance
                FROM core_hospital
                WHERE summary_embedding IS NOT NULL
                ORDER BY summary_embedding <=> %s
                LIMIT %s
                """,
                [query_embedding, query_embedding, top_k]
            )
            for row in cur.fetchall():
                results.append({
                    'type': 'hospital',
                    'id': row[0],
                    'name': row[1],
                    'summary': row[2] or '',
                    'distance': float(row[3]) if row[3] is not None else 0.0,
                })
        # 거리 기준 재정렬 후 상위 top_k * 2 중 distance 기준 상위 top_k (두 모델 통합 랭킹)
        results.sort(key=lambda r: r['distance'])
        return results[:top_k]

    def _search_fallback_python(self, query_embedding: List[float], top_k: int) -> List[Dict[str, Any]]:
        # Postgres 아닌 경우 (예: sqlite 개발 환경) - 파이썬에서 cosine distance 계산
        q = np.array(query_embedding, dtype='float32')
        results: List[Dict[str, Any]] = []
        for obj in Facility.objects.exclude(summary_embedding__isnull=True):
            vec = np.array(obj.summary_embedding, dtype='float32')
            dist = 1 - (np.dot(q, vec) / (np.linalg.norm(q) * np.linalg.norm(vec) + 1e-9))
            results.append({'type': 'facility', 'id': obj.id, 'name': obj.name, 'summary': obj.summary or '', 'distance': float(dist)})
        for obj in Hospital.objects.exclude(summary_embedding__isnull=True):
            vec = np.array(obj.summary_embedding, dtype='float32')
            dist = 1 - (np.dot(q, vec) / (np.linalg.norm(q) * np.linalg.norm(vec) + 1e-9))
            results.append({'type': 'hospital', 'id': obj.id, 'name': obj.name, 'summary': obj.summary or '', 'distance': float(dist)})
        results.sort(key=lambda r: r['distance'])
        return results[:top_k]

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        query_embedding = self.embeddings.embed_query(query)
        if self._pgvector_supported():
            return self._search_postgres(query_embedding, top_k)
        return self._search_fallback_python(query_embedding, top_k)

    # ------------------------- Answer Generation ------------------------- #
    def _build_context(self, items: List[Dict[str, Any]]) -> str:
        context_blocks = []
        for i, item in enumerate(items, 1):
            summary = item['summary'].strip()
            context_blocks.append(f"[{i}] 유형: {item['type']} | 이름: {item['name']}\n요약: {summary}")
        return '\n\n'.join(context_blocks)

    def generate_answer(self, query: str, items: List[Dict[str, Any]]) -> str:
        if not items:
            return '관련된 시설/병원 요약을 찾지 못했습니다.'
        context = self._build_context(items)
        system_msg = SystemMessage(content=(
            '당신은 한국 요양시설 및 요양병원 정보 전문가입니다. '
            '주어진 컨텍스트 내 사실만을 사용해 질문에 답변하고, '
            '시설/병원 이름과 특징을 비교·요약하여 사용자가 선택을 돕도록 하세요.'
        ))
        user_prompt = (
            f"<컨텍스트>\n{context}\n\n"
            f"<사용자 질문>\n{query}\n\n"
            "지침:\n"
            "1. 제공된 문맥 밖 정보는 추론/생성하지 말 것.\n"
            "2. 각 후보의 차별점(등급/특징/서비스)을 항목화.\n"
            "3. 필요한 경우 추천 순위 또는 분류 제시.\n"
            "4. 정보 누락 시 명확히 부족함 언급.\n"
            "5. 간결하지만 핵심 수치/사실 포함.\n"
        )
        human_msg = HumanMessage(content=user_prompt)
        response = self.llm.invoke([system_msg, human_msg])
        return response.content.strip()

    # ------------------------- Public Chat API ------------------------- #
    def chat(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        items = self.search(query, top_k=top_k)
        answer = self.generate_answer(query, items)
        return {
            'query': query,
            'answer': answer,
            'sources': [
                {
                    'rank': idx + 1,
                    'type': item['type'],
                    'id': item['id'],
                    'name': item['name'],
                    'distance': item['distance'],
                } for idx, item in enumerate(items)
            ]
        }

    def stream_chat(self, query: str, top_k: int = 5):
        """검색 + LLM 스트리밍 제너레이터. 각 yield는 dict.
        순서:
          1) {'type':'sources', 'sources': [...]} 첫 전송
          2) {'type':'token', 'text': '...'} 반복 (토큰/청크)
          3) {'type':'end'} 완료
        """
        items = self.search(query, top_k=top_k)
        yield {
            'type': 'sources',
            'sources': [
                {
                    'rank': idx + 1,
                    'type': item['type'],
                    'id': item['id'],
                    'name': item['name'],
                    'distance': item['distance'],
                } for idx, item in enumerate(items)
            ]
        }
        if not items:
            yield {'type': 'token', 'text': '관련된 시설/병원 요약을 찾지 못했습니다.'}
            yield {'type': 'end'}
            return
        context = self._build_context(items)
        system_msg = SystemMessage(content=(
            '당신은 한국 요양시설 및 요양병원 정보 전문가입니다. '
            '주어진 컨텍스트 내 사실만을 사용해 질문에 답변하고, '
            '시설/병원 이름과 특징을 비교·요약하여 사용자가 선택을 돕도록 하세요.'
        ))
        user_prompt = (
            f"<컨텍스트>\n{context}\n\n"
            f"<사용자 질문>\n{query}\n\n"
            "지침:\n"
            "1. 제공된 문맥 밖 정보는 추론/생성하지 말 것.\n"
            "2. 각 후보의 차별점(등급/특징/서비스)을 항목화.\n"
            "3. 필요한 경우 추천 순위 또는 분류 제시.\n"
            "4. 정보 누락 시 명확히 부족함 언급.\n"
            "5. 간결하지만 핵심 수치/사실 포함.\n"
        )
        human_msg = HumanMessage(content=user_prompt)
        try:
            for chunk in self.llm.stream([system_msg, human_msg]):
                if hasattr(chunk, 'content') and chunk.content:
                    yield {'type': 'token', 'text': chunk.content}
        except Exception as e:
            yield {'type': 'token', 'text': f"[오류] {e}"}
        yield {'type': 'end'}

__all__ = ['RAGService']
