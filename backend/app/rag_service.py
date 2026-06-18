import asyncio
import hashlib
import chromadb
from sentence_transformers import SentenceTransformer


import os as _os
_DEFAULT_CHROMA_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "chroma_db")


class RAGService:
    def __init__(self, db_path: str = _DEFAULT_CHROMA_PATH):
        print("[RAG] ko-sroberta 모델 로딩 중...")
        self.model = SentenceTransformer("jhgan/ko-sroberta-multitask")
        self.client = chromadb.PersistentClient(path=db_path)
        self.collection = self.client.get_or_create_collection(
            name="appliance_docs",
            metadata={"hnsw:space": "cosine"},
        )
        print("[RAG] 초기화 완료")

    @staticmethod
    def _make_id(text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def _embed(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, batch_size=4).tolist()

    async def add_documents(self, docs: list[dict]) -> None:
        """
        docs: [{"text": str, "metadata": dict}]
        metadata 권장 키: source, product, category
        """
        if not docs:
            return
        texts = [d["text"] for d in docs]
        ids = [self._make_id(t) for t in texts]
        metadatas = [d.get("metadata", {}) for d in docs]
        try:
            embeddings = await asyncio.to_thread(self._embed, texts)
            await asyncio.to_thread(
                self.collection.upsert,
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
            )
        except Exception as e:
            print(f"[RAG] add_documents 오류: {e}")

    async def query(
        self,
        query_text: str,
        n_results: int = 5,
        where: dict | None = None,
    ) -> list[str]:
        """쿼리와 가장 관련 있는 문서 텍스트 리스트 반환."""
        try:
            total = self.collection.count()
            if total == 0:
                return []
            n = min(n_results, total)
            embedding = await asyncio.to_thread(self._embed, [query_text])
            kwargs: dict = {"query_embeddings": embedding, "n_results": n}
            if where:
                kwargs["where"] = where
            results = await asyncio.to_thread(self.collection.query, **kwargs)
            return results["documents"][0] if results.get("documents") else []
        except Exception as e:
            print(f"[RAG] query 오류: {e}")
            return []
