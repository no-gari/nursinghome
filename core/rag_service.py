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
                    it['image_urls'] = [img.image.url for img in list(f.images.all()[:3])]
                    it['full_location'] = f.location or ''
            else:
                h = hospitals.get(it['id'])
                if h:
                    it['detail_url'] = reverse('core:hospital_detail_by_id', args=[h.id])
                    it['image_urls'] = [img.image.url for img in list(h.images.all()[:3])]
                    it['full_location'] = h.location or ''
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
            if item.get('full_location'):
                meta_parts.append(f"주소:{item['full_location']}")
            meta_line = ' | '.join(meta_parts)
            context_blocks.append(f"[{i}] 유형:{item['type']} | 이름:{item['name']} | {meta_line}\n요약: {summary}")
        return '\n\n'.join(context_blocks)

    def _build_cards(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """프론트에서 카드 형태(UI)로 바로 렌더링할 수 있는 구조 생성.
        기존 sources 보다 풍부한 정보(정원/현원/대기/즉시입소 여부/대표이미지 등)를 담는다.
        """
        cards: List[Dict[str, Any]] = []
        for rank, it in enumerate(items, 1):
            # full_location 우선, 없으면 sido+sigungu
            location = (it.get('full_location') or '').strip()
            if not location:
                location = f"{(it.get('sido') or '').strip()} {(it.get('sigungu') or '').strip()}".strip() or None
            base = {
                'rank': rank,
                'type': it['type'],
                'id': it['id'],
                'code': it.get('code'),
                'name': it['name'],
                'grade': it.get('grade'),
                'summary': it.get('summary', ''),
                'distance': it.get('distance'),
                'detail_url': it.get('detail_url'),
                'image_urls': it.get('image_urls', []),
                'primary_image_url': (it.get('image_urls') or [None])[0],
                'has_images': it.get('has_images'),
                'location': location,
            }
            if it['type'] == 'facility':
                capacity = it.get('capacity')
                occupancy = it.get('occupancy')
                waiting = it.get('waiting')
                immediate = None
                if capacity is not None and occupancy is not None:
                    immediate = (waiting or 0) == 0 and occupancy < capacity
                base.update({
                    'capacity': capacity,
                    'occupancy': occupancy,
                    'waiting': waiting,
                    'immediate_admission': immediate,
                })
            cards.append(base)
        return cards

    def generate_answer(self, query: str, items: List[Dict[str, Any]]) -> str:
        if not items:
            return '관련된 시설/병원 요약을 찾지 못했습니다.'
        context = self._build_context(items)
        system_msg = SystemMessage(content=(
            '당신은 한국 요양시설 및 요양병원 정보 전문가입니다. '
            '주어진 컨텍스트 내 사실만을 사용해 질문에 답변하고, '
            '선정된 시설을 번호 목록 + 간단 불릿(•) 형태로 가독성 있게 요약합니다.'
        ))
        user_prompt = (
            f"<컨텍스트>\n{context}\n\n"
            f"<사용자 질문>\n{query}\n\n"
            "작성 형식 지침:\n"
            "1) 각 시설/병원: '번호. 시설명: 서술형 1~2문장' 뒤에 바로 줄바꿈 후 1~3개의 불릿 라인(• 핵심 프로그램 / • 입소 가능성 / • 평가점수 또는 비용 특징 등).\n"
            "2) 불릿 기호는 반드시 '•' (U+2022) 사용. '-', '*' 등 다른 기호나 표/마크다운 테이블 금지.\n"
            "3) 문장 부분에 등급, 위치(간단 시군구 정도), 정원/현원/대기, 즉시 입소 가능 여부(가능하면 '즉시 입소 가능', 불가하면 '즉시 입소 불가'), 대표 특징 1~2개 자연스럽게 포함.\n"
            "4) 평가 점수/총점 존재 시 한 문장 또는 불릿에 포함 ('평가 95.3점').\n"
            "5) URL 있으면 문장 끝에 (상세: <URL>, 대표사진 있음/없음) 붙임. 실제 이미지 URL 나열 금지.\n"
            "6) 모든 번호 목록 종료 후 빈 줄 1개 뒤 '추천 및 정리:' 로 시작하는 문단 2~3문장 + 선택 추천 1~2곳 근거. 이 요약 문단은 불릿 사용 금지.\n"
            "7) 허구 정보 생성 금지. 모호하면 '정보 없음' 또는 '확인 필요' 간단 명시.\n"
            "8) 전체 출력은 번호 단락 + 불릿 + 마지막 요약만 포함. 그 외 장식/머리글/코드블록 금지.\n"
        )
        human_msg = HumanMessage(content=user_prompt)
        response = self.llm.invoke([system_msg, human_msg])
        return response.content.strip()

    # ------------------------- Public Chat API ------------------------- #
    def chat(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        items = self.search(query, top_k=top_k)
        items = self._enrich_items(items)
        answer = self.generate_answer(query, items)
        cards = self._build_cards(items)
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
            ],
            'cards': cards,
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
        cards = self._build_cards(items)
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
            ],
            'cards': cards,
        }
        if not items:
            yield {'type': 'token', 'text': '관련된 시설/병원 요약을 찾지 못���습니다.'}
            yield {'type': 'end'}
            return
        context = self._build_context(items)
        system_msg = SystemMessage(content=(
            '당신은 한국 요양시설 및 요양병원 정보 전문가입니다. '
            '주어진 컨텍스트 내 사실만을 사용해 번호별 단락 + 불릿(•) 혼합 서식을 생성합니다.'
        ))
        user_prompt = (
            f"<컨텍스트>\n{context}\n\n"
            f"<사용자 질문>\n{query}\n\n"
            "형식 지침:\n"
            "- '번호. 시설명: 1~2문장' + 바로 아래 1~3개 불릿(•). 불릿은 핵심 프로그램, 입소 가능성, 평가점수/특징 중 선택.\n"
            "- 즉시 입소 조건 충족 시 불릿에 '• 즉시 입소 가능', 아니면 '• 즉시 입소 불가' 명시.\n"
            "- URL 표기: 문장 끝 (상세: <URL>, 대표사진 있음/없음).\n"
            "- 모든 번호 끝난 뒤 빈 줄 후 '추천 및 정리:' 문단(불릿 금지) 2~3문장.\n"
            "- 허구 금지, 불확실 시 '정보 없음'.\n"
            "- 다른 장식/표/머리글 금지, 불릿 기호는 반드시 '•'.\n"
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
