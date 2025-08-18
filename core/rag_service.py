import os
import chromadb
from chromadb.config import Settings as ChromaSettings  # 텔레메트리 제어
from sentence_transformers import SentenceTransformer
from django.conf import settings
from core.models import Facility
from typing import List, Dict, Any
import openai
from openai import OpenAI  # OpenAI 1.x Client 추가

class RAGService:
    def __init__(self):
        # ChromaDB 클라이언트 초기화 (텔레메트리 비활성화)
        try:
            self.chroma_client = chromadb.PersistentClient(
                path=str(settings.CHROMA_DB_PATH),
                settings=ChromaSettings(anonymized_telemetry=False)
            )
        except Exception as e:
            print(f"[RAGService] Chroma 클라이언트 초기화 경고(텔레메트리): {e}\n텔레메트리를 완전히 막으려면 환경변수 CHROMA_TELEMETRY_ENABLED=false 설정 권장")
            self.chroma_client = chromadb.PersistentClient(path=str(settings.CHROMA_DB_PATH))
        self.collection_name = "nursinghome_facilities"

        # 임베딩 모델 초기화
        self.embedding_model = SentenceTransformer(settings.EMBEDDING_MODEL)

        # OpenAI 클라이언트 (키가 있을 때만)
        self.openai_client = None
        if settings.OPENAI_API_KEY:
            try:
                self.openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
            except Exception as e:
                print(f"[RAGService] OpenAI 클라이언트 초기화 실패: {e}")

        # 컬렉션 초기화
        self._init_collection()

    def _init_collection(self):
        """ChromaDB 컬렉션 초기화"""
        try:
            # 기존 컬렉션이 있으면 가져��기
            self.collection = self.chroma_client.get_collection(self.collection_name)
        except:
            # 없으면 새로 생성
            self.collection = self.chroma_client.create_collection(
                name=self.collection_name,
                metadata={"description": "요양원 시설 정보"}
            )

    def _clean_text(self, text: str) -> str:
        if not text:
            return ''
        cleaned = text.replace('등��', '등급').replace('\u200b', '').strip()
        return cleaned

    def _chunk_text(self, text: str, chunk_size: int = 1200, overlap: int = 120) -> List[str]:
        """주어진 텍스트를 chunk_size 기준으로 겹치게 분할"""
        chunks = []
        start = 0
        length = len(text)
        while start < length:
            end = start + chunk_size
            chunks.append(text[start:end])
            if end >= length:
                break
            start = end - overlap
        return chunks

    def _legacy_embed_facilities(self, progress_cb=None):
        """구 버전 임베딩 로직"""
        facilities = (Facility.objects
                      .prefetch_related(
                          'basic_items', 'evaluation_items', 'staff_items', 'program_items',
                          'location_items', 'noncovered_items')
                      .select_related('homepage_info')
                      .all())
        if not facilities.exists():
            print('[RAGService] 시설 데이터가 없습니다.')
            if progress_cb:
                progress_cb({"status": "empty", "processed": 0, "total": 0, "failed": 0, "message": "시설 데이터 없음"})
            return 0
        total_fac = facilities.count()
        if progress_cb:
            progress_cb({"status": "running", "stage": "load", "processed": 0, "total": total_fac, "failed": 0, "message": f"총 {total_fac}개 로드"})
        documents, metadatas, ids = [], [], []
        failed = 0
        for idx, facility in enumerate(facilities, 1):
            try:
                doc_parts = [
                    f"시설명: {self._clean_text(facility.name)}",
                    f"시설코드: {facility.code}",
                    f"종류: {self._clean_text(facility.kind) or '정보없음'}",
                    f"등급: {self._clean_text(facility.grade) or '정보없음'}",
                    f"이용가능: {self._clean_text(facility.availability) or '정보없음'}",
                ]
                if facility.capacity: doc_parts.append(f"정원: {facility.capacity}명")
                if facility.occupancy: doc_parts.append(f"현원: {facility.occupancy}명")
                if facility.waiting is not None: doc_parts.append(f"대기: {facility.waiting}명")
                def add_section(title, items):
                    if not items: return
                    valid = [it for it in items if getattr(it, 'content', '').strip()]
                    if not valid: return
                    doc_parts.append(f"\n=== {title} ===")
                    for it in valid:
                        content = self._clean_text(it.content)
                        if len(content) > 800: content = content[:800] + '…'
                        doc_parts.append(f"• {self._clean_text(it.title)}: {content}")
                add_section('기본정보', list(facility.basic_items.all()))
                add_section('평가정보', list(facility.evaluation_items.all()))
                add_section('인력현황', list(facility.staff_items.all()))
                add_section('프로그램 운영', list(facility.program_items.all()))
                add_section('위치정보', list(facility.location_items.all()))
                add_section('비급여 항목', list(facility.noncovered_items.all()))
                homepage = getattr(facility, 'homepage_info', None)
                if homepage and getattr(homepage, 'content', '').strip():
                    hp_content = self._clean_text(homepage.content)
                    if len(hp_content) > 500: hp_content = hp_content[:500] + '…'
                    doc_parts.append("\n=== 홈페이지 ===")
                    doc_parts.append(f"• {self._clean_text(homepage.title)}: {hp_content}")
                documents.append("\n".join(doc_parts))
                metadatas.append({
                    "facility_id": facility.id,
                    "facility_code": facility.code,
                    "facility_name": facility.name,
                    "facility_kind": facility.kind or '',
                    "facility_grade": facility.grade or '',
                    "facility_availability": facility.availability or ''
                })
                ids.append(f"facility_{facility.id}")
            except Exception as e:
                failed += 1
                if progress_cb:
                    progress_cb({"status": "running", "stage": "collect", "processed": idx-1, "total": total_fac, "failed": failed, "message": f"시설 처리 실패 {facility.id}:{e}"})
                continue
            if progress_cb and idx % 50 == 0:
                progress_cb({"status": "running", "stage": "collect", "processed": idx, "total": total_fac, "failed": failed, "message": f"{idx}/{total_fac} 수집"})
        if progress_cb:
            progress_cb({"status": "running", "stage": "recreate_collection", "processed": len(documents), "total": total_fac, "failed": failed, "message": "컬렉션 재생성"})
        try:
            try:
                self.chroma_client.delete_collection(name=self.collection_name)
            except Exception:
                pass
            self.collection = self.chroma_client.create_collection(name=self.collection_name, metadata={"description": "요양원 시설 정보"})
        except Exception as e:
            if progress_cb:
                progress_cb({"status": "error", "stage": "recreate_collection", "processed": 0, "total": total_fac, "failed": failed, "message": f"컬렉션 실패: {e}"})
            return 0
        batch_size = 50
        added = 0
        for i in range(0, len(documents), batch_size):
            batch_docs = documents[i:i+batch_size]
            batch_meta = metadatas[i:i+batch_size]
            batch_ids = ids[i:i+batch_size]
            try:
                embeddings = self.embedding_model.encode(batch_docs).tolist()
                self.collection.add(documents=batch_docs, metadatas=batch_meta, ids=batch_ids, embeddings=embeddings)
                added += len(batch_docs)
                if progress_cb:
                    progress_cb({"status": "running", "stage": "embedding", "processed": added, "total": total_fac, "failed": failed, "message": f"임베딩 {added}/{len(documents)}"})
            except Exception as e:
                failed += len(batch_docs)
                if progress_cb:
                    progress_cb({"status": "running", "stage": "embedding", "processed": added, "total": total_fac, "failed": failed, "message": f"배치 오류: {e}"})
        if progress_cb:
            progress_cb({"status": "finished", "stage": "done", "processed": added, "total": total_fac, "failed": failed, "message": f"완료 (성공 {added} / 실패 {failed})"})
        return added

    def embed_facilities(self, progress_cb=None):
        """모든 요양원 데이터를 벡터화 (모든 1-depth 관계 포함)"""
        select_related_fields: List[str] = []
        prefetch_related_fields: List[str] = []
        for field in Facility._meta.get_fields():
            if not field.is_relation:
                continue
            if field.many_to_one or field.one_to_one:
                select_related_fields.append(field.name)
            else:
                if field.auto_created:
                    prefetch_related_fields.append(field.get_accessor_name())
                else:
                    prefetch_related_fields.append(field.name)

        facilities = (Facility.objects
                      .select_related(*select_related_fields)
                      .prefetch_related(*prefetch_related_fields)
                      .all())
        if not facilities.exists():
            print('[RAGService] 시설 데이터가 없습니다.')
            if progress_cb:
                progress_cb({"status": "empty", "processed": 0, "total": 0, "failed": 0, "message": "시설 데이터 없음"})
            return 0

        total_fac = facilities.count()
        if progress_cb:
            progress_cb({"status": "running", "stage": "load", "processed": 0, "total": total_fac, "failed": 0, "message": f"총{total_fac}개 로드"})

        documents: List[str] = []
        metadatas: List[Dict[str, Any]] = []
        ids: List[str] = []
        failed = 0

        for idx, facility in enumerate(facilities, 1):
            try:
                base_parts = [
                    f"시설명: {self._clean_text(facility.name)}",
                    f"시설코드: {facility.code}",
                    f"종류: {self._clean_text(facility.kind) or '정보없음'}",
                    f"등급: {self._clean_text(facility.grade) or '정보없음'}",
                    f"이용가능: {self._clean_text(facility.availability) or '정보없음'}",
                ]
                if facility.capacity:
                    base_parts.append(f"정원: {facility.capacity}명")
                if facility.occupancy:
                    base_parts.append(f"현원: {facility.occupancy}명")
                if facility.waiting is not None:
                    base_parts.append(f"대기: {facility.waiting}명")

                for field in Facility._meta.get_fields():
                    if not field.is_relation:
                        continue
                    related_objects = []
                    if field.many_to_one or field.one_to_one:
                        obj = getattr(facility, field.name, None)
                        if obj:
                            related_objects.append(obj)
                    else:
                        manager = getattr(facility, field.get_accessor_name() if field.auto_created else field.name)
                        try:
                            related_objects.extend(list(manager.all()))
                        except Exception:
                            continue
                    for obj in related_objects:
                        if isinstance(obj, Facility):
                            continue
                        title = self._clean_text(getattr(obj, 'title', ''))
                        content = self._clean_text(getattr(obj, 'content', ''))
                        if title or content:
                            base_parts.append(f"{title} : {content}")

                full_text = "\n".join(base_parts)
                chunks = self._chunk_text(full_text)
                for c_idx, chunk in enumerate(chunks):
                    documents.append(chunk)
                    metadatas.append({
                        "facility_id": facility.id,
                        "facility_code": facility.code,
                        "facility_name": facility.name,
                        "facility_kind": facility.kind or '',
                        "facility_grade": facility.grade or '',
                        "facility_availability": facility.availability or ''
                    })
                    ids.append(f"facility_{facility.id}_{c_idx}")
            except Exception as e:
                failed += 1
                if progress_cb:
                    progress_cb({"status": "running", "stage": "collect", "processed": idx-1, "total": total_fac, "failed": failed, "message": f"시설 처리 실패 {facility.id}:{e}"})
                continue

            if progress_cb and idx % 50 == 0:
                progress_cb({"status": "running", "stage": "collect", "processed": idx, "total": total_fac, "failed": failed, "message": f"{idx}/{total_fac} 수집"})

        if progress_cb:
            progress_cb({"status": "running", "stage": "recreate_collection", "processed": len(documents), "total": total_fac, "failed": failed, "message": "컬렉션 재생성"})

        try:
            try:
                self.chroma_client.delete_collection(name=self.collection_name)
            except Exception:
                pass
            self.collection = self.chroma_client.create_collection(name=self.collection_name, metadata={"description": "요양원 시설 정보"})
        except Exception as e:
            if progress_cb:
                progress_cb({"status": "error", "stage": "recreate_collection", "processed": 0, "total": total_fac, "failed": failed, "message": f"컬렉션 실패: {e}"})
            return 0

        batch_size = 50
        added = 0
        for i in range(0, len(documents), batch_size):
            batch_docs = documents[i:i + batch_size]
            batch_meta = metadatas[i:i + batch_size]
            batch_ids = ids[i:i + batch_size]
            try:
                emb_inputs = [f"passage: {doc}" for doc in batch_docs]
                embeddings = self.embedding_model.encode(emb_inputs).tolist()
                self.collection.add(documents=batch_docs, metadatas=batch_meta, ids=batch_ids, embeddings=embeddings)
                added += len(batch_docs)
                if progress_cb:
                    progress_cb({"status": "running", "stage": "embedding", "processed": added, "total": total_fac, "failed": failed, "message": f"임베딩 {added}/{len(documents)}"})
            except Exception as e:
                failed += len(batch_docs)
                if progress_cb:
                    progress_cb({"status": "running", "stage": "embedding", "processed": added, "total": total_fac, "failed": failed, "message": f"배치 오류: {e}"})

        if progress_cb:
            progress_cb({"status": "finished", "stage": "done", "processed": added, "total": total_fac, "failed": failed, "message": f"완료 (성공 {added} / 실패 {failed})"})
        return added

    def search_facilities(self, query: str, n_results: int = 5) -> List[Dict]:
        """사용자 질문에 관련된 요양원들을 검색"""
        # 쿼리 임베딩 (prefix 적용)
        query_embedding = self.embedding_model.encode([f"query: {query}"]).tolist()

        # 유사한 문서 검색
        results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=n_results,
            include=['documents', 'metadatas', 'distances']
        )

        return results

    def generate_answer(self, query: str, context_docs: List[str]) -> str:
        """검색된 문서들을 바탕으로 답변 생성 (OpenAI 없으면 규칙기반 요약)"""
        # OpenAI 키가 없으면 간단 요약 fallback
        if not self.openai_client:
            highlights = []
            for doc in context_docs[:5]:
                # 첫 줄(시설명)만 추출
                first_line = doc.split('\n', 1)[0].strip()
                highlights.append(f"- {first_line}")
            return (
                "(LLM 미사용 요약 모드)\n" +\
                "관련 시설 개요:\n" + "\n".join(highlights) + "\n" +
                "보다 자세한 설명을 원하시면 OpenAI API 키를 설정해주세요."
            )

        # OpenAI 사용 프롬프트 구성
        context = "\n\n".join([f"[시설 {i+1}]\n{doc}" for i, doc in enumerate(context_docs)])
        prompt = f"""
다음은 한국의 요양원 시설 정보입니다. 사용자의 질문에 대해 이 정보를 바탕으로 정확하고 도움이 되는 답변을 제공해주세요.

<요양원 정보>
{context}

<사용자 질문>
{query}

<답변 가이드라인>
1. 제공된 정보만을 바탕으로 답변하세요
2. 구체적인 시설명, 등급, 위치 등을 포함하여 답변하세요
3. 사용자가 요양원 선택에 도움이 되도록 비교 정보를 제공하세요
4. 정보가 부족한 경우 솔직히 말씀드리세요
5. 친근하고 전문적인 톤으로 답변하세요
6. 가능하면 추천 순위나 우선순위�� 매겨서 제시하세요
7. 각 시설의 특징과 장단점을 명확히 설명하세요

답변:
""".strip()
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "당신은 요양원 정보 전문가입니다. 사용자가 적절한 요양원을 찾을 수 있도록 정확하고 유용한 정보를 제공합니다. 답변은 체계적이고 이해하기 쉽게 구성하세요."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1200,  # 900 → 1200으로 증가 (더 자세한 답변)
                temperature=0.3,  # 0.6 → 0.3으로 낮춤 (더 일관된 답변)
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"답변 생성 중 오류가 발생했습니다: {e}"

    def chat(self, query: str) -> Dict[str, Any]:
        """전체 RAG 프로세스 실행"""
        # 1. 관련 문서 검색
        search_results = self.search_facilities(query)

        # 2. 검색 결과가 있는지 확인
        if not search_results['documents'][0]:
            return {
                "answer": "죄송합니다. 질문과 관련된 요양원 정보를 찾을 수 없습니다.",
                "sources": [],
                "query": query
            }

        # 3. 컨���스트 문서 준비
        context_docs = search_results['documents'][0]
        metadatas = search_results['metadatas'][0]

        # 4. LLM으로 답변 생성
        answer = self.generate_answer(query, context_docs)

        # 5. 결과 반환
        return {
            "answer": answer,
            "sources": [
                {
                    "facility_name": meta['facility_name'],
                    "facility_grade": meta['facility_grade'],
                    "facility_id": meta['facility_id']
                } for meta in metadatas
            ],
            "query": query
        }
