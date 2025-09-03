import re
import logging
from typing import List, Dict, Any

from django.conf import settings
from django.db import connection
from django.urls import reverse

import numpy as np

from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage

from core.models import Facility, Hospital

logger = logging.getLogger(__name__)


class RAGService:
    """LangChain + OpenAI 임���딩 + pgvector(summary_embedding) 기반 RAG 서비스.

    흐름:
      1) Facility / Hospital.summary 전체 문자열 임베딩
      2) summary_embedding 저장
      3) 검색 시 query 임베딩과 cosine 검색
      4) LLM 답변 (단일/다중 모드 분기)
    """

    EMBEDDING_MODEL = getattr(settings, 'OPENAI_EMBEDDING_MODEL', 'text-embedding-3-small')
    LLM_MODEL = getattr(settings, 'OPENAI_LLM_MODEL', 'gpt-4o-mini')

    def __init__(self):
        api_key = getattr(settings, 'OPENAI_API_KEY', None)
        if not api_key:
            raise RuntimeError('OPENAI_API_KEY 가 settings 에 설정되어 있어야 합니다.')
        self.embeddings = OpenAIEmbeddings(model=self.EMBEDDING_MODEL, api_key=api_key)
        self.llm = ChatOpenAI(model=self.LLM_MODEL, temperature=0.3, api_key=api_key)
        self.classifier_llm = ChatOpenAI(model=self.LLM_MODEL, temperature=0, api_key=api_key)

    # ------------------------- Search ------------------------- #
    def _pgvector_supported(self) -> bool:
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
                    'type': 'facility', 'id': row[0], 'code': row[1], 'name': row[2], 'summary': row[3] or '',
                    'has_images': row[4], 'waiting': row[5], 'capacity': row[6], 'occupancy': row[7], 'grade': row[8],
                    'sido': row[9], 'sigungu': row[10], 'distance': float(row[11]) if row[11] is not None else 0.0,
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
                    'type': 'hospital', 'id': row[0], 'code': row[1], 'name': row[2], 'summary': row[3] or '',
                    'has_images': row[4], 'grade': row[5], 'sido': row[6], 'sigungu': row[7],
                    'distance': float(row[8]) if row[8] is not None else 0.0,
                })
        results.sort(key=lambda r: r['distance'])
        return results[:top_k]

    def _search_fallback_python(self, query_embedding: List[float], top_k: int) -> List[Dict[str, Any]]:
        q = np.array(query_embedding, dtype='float32')
        results: List[Dict[str, Any]] = []
        def cos_dist(vec):
            v = np.array(vec, dtype='float32')
            return 1 - (np.dot(q, v) / (np.linalg.norm(q) * np.linalg.norm(v) + 1e-9))
        for f in Facility.objects.exclude(summary_embedding__isnull=True):
            results.append({
                'type': 'facility', 'id': f.id, 'code': f.code, 'name': f.name, 'summary': f.summary or '',
                'has_images': f.has_images, 'waiting': f.waiting, 'capacity': f.capacity, 'occupancy': f.occupancy,
                'grade': f.grade, 'sido': f.sido, 'sigungu': f.sigungu,
                'distance': cos_dist(f.summary_embedding)
            })
        for h in Hospital.objects.exclude(summary_embedding__isnull=True):
            results.append({
                'type': 'hospital', 'id': h.id, 'code': h.code, 'name': h.name, 'summary': h.summary or '',
                'has_images': h.has_images, 'grade': h.grade, 'sido': h.sido, 'sigungu': h.sigungu,
                'distance': cos_dist(h.summary_embedding)
            })
        results.sort(key=lambda r: r['distance'])
        return results[:top_k]

    def search(self, query: str, top_k: int = 8) -> List[Dict[str, Any]]:
        embedding = self.embeddings.embed_query(query)
        if self._pgvector_supported():
            try:
                return self._search_postgres(embedding, top_k)
            except Exception as e:
                logger.warning(f"pgvector 검색 실패 -> fallback: {e}")
        return self._search_fallback_python(embedding, top_k)

    # ------------------------- Enrich / Cards ------------------------- #
    def _enrich_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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

    def _build_cards(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cards = []
        for rank, it in enumerate(items, 1):
            loc = (it.get('full_location') or '').strip()
            if not loc:
                loc = f"{(it.get('sido') or '').strip()} {(it.get('sigungu') or '').strip()}".strip() or None
            card = {
                'rank': rank, 'type': it['type'], 'id': it['id'], 'code': it.get('code'), 'name': it['name'],
                'grade': it.get('grade'), 'summary': it.get('summary', ''), 'distance': it.get('distance'),
                'detail_url': it.get('detail_url'), 'image_urls': it.get('image_urls', []),
                'primary_image_url': (it.get('image_urls') or [None])[0], 'has_images': it.get('has_images'),
                'location': loc,
            }
            if it['type'] == 'facility':
                cap = it.get('capacity'); occ = it.get('occupancy'); wait = it.get('waiting')
                immediate = None
                if cap is not None and occ is not None:
                    immediate = (wait or 0) == 0 and occ < cap
                card.update({'capacity': cap, 'occupancy': occ, 'waiting': wait, 'immediate_admission': immediate})
            cards.append(card)
        return cards

    # ------------------------- Context Builder ------------------------- #
    def _build_context(self, items: List[Dict[str, Any]]) -> str:
        blocks = []
        for i, item in enumerate(items, 1):
            meta = []
            if item['type'] == 'facility':
                cap = item.get('capacity'); occ = item.get('occupancy'); wait = item.get('waiting')
                immediate = None
                if cap is not None and occ is not None:
                    immediate = (wait or 0) == 0 and occ < cap
                meta.append(f"등급:{item.get('grade') or '정보없음'}")
                if cap is not None: meta.append(f"정원:{cap}")
                if occ is not None: meta.append(f"현원:{occ}")
                if wait is not None: meta.append(f"대기:{wait}")
                if immediate is not None: meta.append(f"즉시입소:{'예' if immediate else '불명'}")
            else:
                meta.append(f"등급:{item.get('grade') or '정보없음'}")
            meta.append(f"이미지:{'Y' if item.get('has_images') else 'N'}")
            if item.get('detail_url'): meta.append(f"상세:{item['detail_url']}")
            if item.get('image_urls'): meta.append(f"사진예시:{item['image_urls'][0]}")
            if item.get('full_location'): meta.append(f"주소:{item['full_location']}")
            blocks.append(
                f"[{i}] 유형:{item['type']} | 이름:{item['name']} | " + ' | '.join(meta) + f"\n요약: {item.get('summary','').strip()}"
            )
        return '\n\n'.join(blocks)

    # ------------------------- Mode Detection ------------------------- #
    def _is_single_entity_query(self, query: str, items: List[Dict[str, Any]]) -> bool:
        if not items:
            return False
        if len(items) == 1:
            return True
        names = [it['name'] for it in items[:5]]
        def norm(s: str):
            return re.sub(r'\s+', '', (s or '')).lower()
        qn = norm(query)
        matched = [n for n in names if norm(n) and norm(n) in qn]
        if len(matched) == 1:
            return True
        try:
            d1, d2 = items[0]['distance'], items[1]['distance']
            if (d2 - d1) > 0.07 or (d1 < 0.35 and (d2 / (d1 + 1e-6)) > 1.25):
                return True
        except Exception:
            pass
        keywords = ["정보", "상세", "자세", "소개", "어때", "어떤", "평가"]
        if any(k in query for k in keywords):
            tokens = [t for t in re.split(r'[^가-힣A-Za-z0-9]+', items[0]['name']) if len(t) >= 2]
            if any(t in query for t in tokens):
                return True
        return False

    def _llm_classify_mode(self, query: str, items: List[Dict[str, Any]]) -> str:
        if not items:
            return 'list'
        cand_lines = []
        for i, it in enumerate(items[:5], 1):
            cand_lines.append(f"{i}. {it['name']} (distance={it['distance']:.4f})")
        system = SystemMessage(content=(
            "너는 분류기다. 질문이 특정 단일 시설/병원 하나의 상세 정보만 요구하면 SINGLE, 아니면 LIST. "
            "출력은 JSON 한 줄: {\"mode\": \"SINGLE\"} 또는 {\"mode\": \"LIST\"}. 다른 텍스트 금지."
        ))
        user = HumanMessage(content=(
            f"[질문]\n{query}\n\n[후보]\n" + '\n'.join(cand_lines) + "\n\n기준:\n" \
            "SINGLE: 특정 고유명 + 상세/소개/평가/정보/어때 등.\n" \
            "LIST: 비교/추천/여러개/지역조건/모호탐색.\nJSON만."))
        try:
            resp = self.classifier_llm.invoke([system, user])
            txt = (resp.content or '').upper()
            if 'SINGLE' in txt:
                return 'single'
            if 'LIST' in txt:
                return 'list'
        except Exception:
            return 'list'
        return 'list'

    # ------------------------- Stream Chat ------------------------- #
    def stream_chat(self, query: str, top_k: int = 8):
        items = self.search(query, top_k=top_k)
        items = self._enrich_items(items)
        mode_llm = self._llm_classify_mode(query, items)
        single_mode = (mode_llm == 'single') or (mode_llm == 'list' and self._is_single_entity_query(query, items))
        if single_mode and items:
            items = items[:1]
        cards = self._build_cards(items)
        yield {
            'type': 'sources',
            'mode': 'single' if single_mode else 'list',
            'classifier_mode': mode_llm,
            'sources': [
                {
                    'rank': idx + 1,
                    'type': it['type'],
                    'id': it['id'],
                    'code': it.get('code'),
                    'name': it['name'],
                    'distance': it['distance'],
                    'detail_url': it.get('detail_url'),
                    'image_urls': it.get('image_urls', []),
                    'has_images': it.get('has_images'),
                } for idx, it in enumerate(items)
            ],
            'cards': cards,
        }
        if not items:
            yield {'type': 'token', 'text': '관련된 시설/병원 요약을 찾지 못했습니다.'}
            yield {'type': 'end'}
            return
        context = self._build_context(items)
        if single_mode:
            system_msg = SystemMessage(content=(
                '당신은 한국 요양시설 및 요양병원 정보 전문가입니다. 특정 한 곳의 사실 기반 실용 정보를 제공합니다.'
            ))
            user_prompt = (
                f"<대상 컨텍스트>\n{context}\n\n<사용자 질문>\n{query}\n\n" \
                "작성 지침:\n" \
                "1) h2로 이름 제목.\n" \
                "2) 3~4문장: 위치, 등급/평가, 규모(정원/현원/대기), 특화 서비스, 즉시입소 가능성(확실할 때만).\n" \
                "3) 간단한 문장 4~6개:\n- 입소 가능 여부 (모호하면 '정보 없음')\n- 등급/평가 핵심 (없으면 '정보 없음')\n- 주요 프로그램/특화 서비스 (없으면 '정보 없음')\n- 규모와 즉시입소 판단 근거\n- 추가 의사결정 포인트(이미지/홈페이지/주소 등)\n" \
                "4) 추측 금지: 없으면 '정보 없음'.\n5) 다른 곳 비교/추천 금지." )
        else:
            system_msg = SystemMessage(content=(
                '당신은 한국 요양시설 및 요양병원 정보 전문가입니다. 다중 후보를 구조적으로 비교·요약합니다.'
            ))
            user_prompt = (
                f"<컨텍스트>\n{context}\n\n<사용자 질문>\n{query}\n\n" \
                "작성 형식 지침:\n" \
                "1) 각 시설/병원: h2 제목 + 아래 2~3문장 (위치, 등급, 규모, 특징).\n" \
                "2) 바로 아래 3~4개의 bullet points: 입소 가능 여부, 등급/평가, 프로그램/특화, 규모/운영 특징.\n" \
                "3) 모든 소개 후 빈 줄 두고 h2 '정리' 섹션: 2~3개 h3 추천 + 근거/장점/고려사항.\n" \
                "4) 컨텍스트 밖/추측 금지. 불확실: '확인 필요' 또는 '정보 없음'." )
        human_msg = HumanMessage(content=user_prompt)
        try:
            for chunk in self.llm.stream([system_msg, human_msg]):
                if hasattr(chunk, 'content') and chunk.content:
                    yield {'type': 'token', 'text': chunk.content}
        except Exception as e:
            yield {'type': 'token', 'text': f"[오류] {e}"}
        yield {'type': 'end'}

    # ------------------------- Embedding Update ------------------------- #
    def update_all_embeddings(self, force: bool = False) -> Dict[str, int]:
        upd_fac = upd_hos = 0
        def need(o): return force or not o.summary_embedding
        for f in Facility.objects.all():
            if f.summary and need(f):
                try:
                    f.summary_embedding = self.embeddings.embed_query(f.summary)
                    f.save(update_fields=['summary_embedding'])
                    upd_fac += 1
                except Exception as e:
                    logger.warning(f"Facility {f.id} 임베딩 실패: {e}")
        for h in Hospital.objects.all():
            if h.summary and need(h):
                try:
                    h.summary_embedding = self.embeddings.embed_query(h.summary)
                    h.save(update_fields=['summary_embedding'])
                    upd_hos += 1
                except Exception as e:
                    logger.warning(f"Hospital {h.id} 임베딩 실패: {e}")
        return {'facility': upd_fac, 'hospital': upd_hos}

__all__ = ['RAGService']
