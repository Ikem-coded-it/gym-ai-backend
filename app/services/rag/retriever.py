import os
from dotenv import load_dotenv
from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from pinecone import Pinecone
from pydantic import Field
from typing import List
from app.logger import logger

load_dotenv()

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME")
PINECONE_NAMESPACE = os.getenv("PINECONE_NAMESPACE")
TOP_K = int(os.getenv("TOP_K", "3"))

class PineconeRetriever(BaseRetriever):
    index: any = Field(description="Pinecone index")
    top_k: int = Field(default=TOP_K, description="Number of results to return")
    namespace: str = Field(default=PINECONE_NAMESPACE)

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> List[Document]:
        # Search Pinecone using integrated inference
        results = self.index.search(
            namespace=self.namespace,
            query={
                "inputs": {"text": query},  # Pinecone embeds this automatically
                "top_k": self.top_k
            },
            fields=["content", "category"]  # fields to return
        )
        # logger.info(f"Results: {results}")

        hits = []
        if isinstance(results, dict):
            hits = results.get("result", {}).get("hits", [])
        else:
            result = getattr(results, "result", None)
            if result is not None:
                hits = getattr(result, "hits", [])

        documents = []
        for match in hits:
            if isinstance(match, dict):
                fields = match.get("fields", {})
                page_content = fields.get("content", "")
                metadata = {
                    "score": match.get("score"),
                    "category": fields.get("category", ""),
                    "id": match.get("id"),
                }
            else:
                fields = getattr(match, "fields", {}) or {}
                page_content = fields.get("content", "")
                metadata = {
                    "score": getattr(match, "score", None),
                    "category": fields.get("category", ""),
                    "id": getattr(match, "id", None),
                }

            documents.append(
                Document(page_content=page_content, metadata=metadata)
            )

        return documents

def create_retriever():
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)

    return PineconeRetriever(
        index=index,
        top_k=TOP_K,
        namespace=PINECONE_NAMESPACE
    )