import re
import logging
from typing import List, Dict, Any, Sequence  # Sequence 미사용 가능하지만 유지

from django.conf import settings
from django.db import connection
from django.db.models import QuerySet
from django.urls import reverse

import numpy as np

from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage

from core.models import Facility, Hospital

logger = logging.getLogger(__name__)


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
        vec_literal = '[' + ','.join(f'{x:.6f}' for x in query_embedding) + ']'
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT id, code, name, summary, has_images, waiting, capacity, occupancy, grade, sido, sigungu,
                       (summary_embedding <=> %s::vector) AS distance
                FROM core_facility
                WHERE summary_embedding IS NOT NULL
                ORDER BY summary_embedding <=> %s::vector
                LIMIT %s
                """,
                [vec_literal, vec_literal, top_k]
            )
            for row in cur.fetchall():
                results.append({
                    'type': 'facility',
                    'id': row[0],
                    'code': row[1],
                    'name': row[2],
                    'summary': row[3] or '',
                    'has_images': row[4],
                    'waiting': row[5],
                    'capacity': row[6],
                    'occupancy': row[7],
                    'grade': row[8],
                    'sido': row[9],
                    'sigungu': row[10],
                    'distance': float(row[11]) if row[11] is not None else 0.0,
                })
        with connection.cursor() as cur:
            cur.execute(
                """
                SELECT id, code, name, summary, has_images, grade, sido, sigungu,
                       (summary_embedding <=> %s::vector) AS distance
                FROM core_hospital
                WHERE summary_embedding IS NOT NULL
                ORDER BY summary_embedding <=> %s::vector
                LIMIT %s
                """,
                [vec_literal, vec_literal, top_k]
            )
            for row in cur.fetchall():
                results.append({
                    'type': 'hospital',
                    'id': row[0],
                    'code': row[1],
                    'name': row[2],
                    'summary': row[3] or '',
                    'has_images': row[4],
                    'grade': row[5],
                    'sido': row[6],
                    'sigungu': row[7],
                    'distance': float(row[8]) if row[8] is not None else 0.0,
                })
        results.sort(key=lambda r: r['distance'])
        return results[:top_k]

    def _search_fallback_python(self, query_embedding: List[float], top_k: int) -> List[Dict[str, Any]]:
        # Postgres 아닌 경우 (예: sqlite 개발 환경) - 파이썬에서 cosine distance 계산
        q = np.array(query_embedding, dtype='float32')
        results: List[Dict[str, Any]] = []
        for obj in Facility.objects.exclude(summary_embedding__isnull=True):
            vec = np.array(obj.summary_embedding, dtype='float32')
            dist = 1 - (np.dot(q, vec) / (np.linalg.norm(q) * np.linalg.norm(vec) + 1e-9))
            results.append({
                'type': 'facility',
                'id': obj.id,
                'code': obj.code,
                'name': obj.name,
                'summary': obj.summary or '',
                'has_images': obj.has_images,
                'waiting': obj.waiting,
                'capacity': obj.capacity,
                'occupancy': obj.occupancy,
                'grade': obj.grade,
                'sido': obj.sido,
                'sigungu': obj.sigungu,
                'distance': float(dist)
            })
        for obj in Hospital.objects.exclude(summary_embedding__isnull=True):
            vec = np.array(obj.summary_embedding, dtype='float32')
            dist = 1 - (np.dot(q, vec) / (np.linalg.norm(q) * np.linalg.norm(vec) + 1e-9))
            results.append({
                'type': 'hospital',
                'id': obj.id,
                'code': obj.code,
                'name': obj.name,
                'summary': obj.summary or '',
                'has_images': obj.has_images,
                'grade': obj.grade,
                'sido': obj.sido,
                'sigungu': obj.sigungu,
                'distance': float(dist)
            })
        results.sort(key=lambda r: r['distance'])
        return results[:top_k]

    def _enrich_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """상세 페이지 링크, 이미지 URL 등 부가정보 추가"""
        facility_ids = [i['id'] for i in items if i['type'] == 'facility']
        hospital_ids = [i['id'] for i in items if i['type'] == 'hospital']
        facilities = {f.id: f for f in Facility.objects.filter(id__in=facility_ids).prefetch_related('images')}
        hospitals = {h.id: h for h in Hospital.objects.filter(id__in=hospital_ids).prefetch_related('images')}
        for it in items:
            if it['type'] == 'facility':
                f = facilities.get(it['id'])
                if f:
                    it['detail_url'] = reverse('core:facility_detail', args=[f.code])
                    # 대표 이미지 최대 3장
                    it['image_urls'] = [img.image.url for img in list(f.images.all()[:3])]
            else:
                h = hospitals.get(it['id'])
                if h:
                    # 병원 상세는 id 기반 URL 사용
                    it['detail_url'] = reverse('core:hospital_detail_by_id', args=[h.id])
                    it['image_urls'] = [img.image.url for img in list(h.images.all()[:3])]
        return items

    # ------------------------- Answer Generation ------------------------- #
    def _build_context(self, items: List[Dict[str, Any]]) -> str:
        context_blocks = []
        for i, item in enumerate(items, 1):
            summary = item['summary'].strip()
            meta_parts = []
            if item['type'] == 'facility':
                # 정원/현원/대기 기반 즉시입소 판단
                capacity = item.get('capacity')
                occupancy = item.get('occupancy')
                waiting = item.get('waiting')
                immediate = None
                if capacity is not None and occupancy is not None:
                    immediate = (waiting or 0) == 0 and occupancy < capacity
                meta_parts.append(f"등급:{item.get('grade') or '정보없음'}")
                if capacity is not None:
                    meta_parts.append(f"정원:{capacity}")
                if occupancy is not None:
                    meta_parts.append(f"현원:{occupancy}")
                if waiting is not None:
                    meta_parts.append(f"대기:{waiting}")
                if immediate is not None:
                    meta_parts.append(f"즉시입소:{'예' if immediate else '불명'}")
            else:
                meta_parts.append(f"등급:{item.get('grade') or '정보없음'}")
            meta_parts.append(f"이미지:{'Y' if item.get('has_images') else 'N'}")
            if item.get('detail_url'):
                meta_parts.append(f"상세:{item['detail_url']}")
            if item.get('image_urls'):
                meta_parts.append(f"사진예시:{item['image_urls'][0]}")
            meta_line = ' | '.join(meta_parts)
            context_blocks.append(f"[{i}] 유형:{item['type']} | 이름:{item['name']} | {meta_line}\n요약: {summary}")
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
            "6. 각 후보 서술 마지막 줄에 `상세: <URL>` 및 대표 사진이 있으면 `대표사진: <URL>` 명시 (sources.detail_url, sources.image_urls[0] 사용).\n"
        )
        human_msg = HumanMessage(content=user_prompt)
        response = self.llm.invoke([system_msg, human_msg])
        return response.content.strip()

    # ------------------------- Public Chat API ------------------------- #
    def chat(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        items = self.search(query, top_k=top_k)
        items = self._enrich_items(items)
        answer = self.generate_answer(query, items)
        return {
            'query': query,
            'answer': answer,
            'sources': [
                {
                    'rank': idx + 1,
                    'type': item['type'],
                    'id': item['id'],
                    'code': item.get('code'),
                    'name': item['name'],
                    'distance': item['distance'],
                    'detail_url': item.get('detail_url'),
                    'image_urls': item.get('image_urls', []),
                    'has_images': item.get('has_images'),
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
        items = self._enrich_items(items)
        yield {
            'type': 'sources',
            'sources': [
                {
                    'rank': idx + 1,
                    'type': item['type'],
                    'id': item['id'],
                    'code': item.get('code'),
                    'name': item['name'],
                    'distance': item['distance'],
                    'detail_url': item.get('detail_url'),
                    'image_urls': item.get('image_urls', []),
                    'has_images': item.get('has_images'),
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
            "6. 각 후보 서술 마지막 줄에 `상세: <URL>` 및 대표 사진이 있으면 `대표사진: <URL>` 명시 (sources.detail_url, sources.image_urls[0] 사용).\n"
        )
        human_msg = HumanMessage(content=user_prompt)
        try:
            for chunk in self.llm.stream([system_msg, human_msg]):
                if hasattr(chunk, 'content') and chunk.content:
                    yield {'type': 'token', 'text': chunk.content}
        except Exception as e:
            yield {'type': 'token', 'text': f"[오류] {e}"}
        yield {'type': 'end'}

    def update_all_embeddings(self, force: bool = False) -> Dict[str, int]:
        """Facility / Hospital summary 임베딩 생성 또는 갱신.
        force=True 이면 기존 embedding 재계산.
        반환: {'facility': 갱신건수, 'hospital': 갱신건수}
        """
        updated_fac, updated_hos = 0, 0

        def need(obj):
            return force or not obj.summary_embedding

        # Facility
        for f in Facility.objects.all():
            if f.summary and need(f):
                try:
                    f.summary_embedding = self.embeddings.embed_query(f.summary)
                    f.save(update_fields=['summary_embedding'])
                    updated_fac += 1
                except Exception as e:
                    logger.warning(f"Facility {f.id} 임베딩 실패: {e}")
        # Hospital
        for h in Hospital.objects.all():
            if h.summary and need(h):
                try:
                    h.summary_embedding = self.embeddings.embed_query(h.summary)
                    h.save(update_fields=['summary_embedding'])
                    updated_hos += 1
                except Exception as e:
                    logger.warning(f"Hospital {h.id} 임베딩 실패: {e}")
        return {'facility': updated_fac, 'hospital': updated_hos}

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Query 임베딩 생성 후 pgvector(or 파이썬) 코사인 거리로 상위 top_k 반환."""
        query_embedding = self.embeddings.embed_query(query)
        if self._pgvector_supported():
            try:
                return self._search_postgres(query_embedding, top_k)
            except Exception as e:
                logger.warning(f"pgvector 검색 실패, 파이썬 fallback 사용: {e}")
        return self._search_fallback_python(query_embedding, top_k)

__all__ = ['RAGService']
