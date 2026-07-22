import os
from dotenv import load_dotenv
from langchain_core.retrievers import BaseRetriever
from langchain_core.documents import Document
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from pinecone import Pinecone
from pydantic import Field
from typing import List

load_dotenv()

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME")
PINECONE_NAMESPACE = os.getenv("PINECONE_NAMESPACE")
TOP_K = os.getenv("TOP_K")

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
        print("results", results)

        # Convert results to LangChain Document objects
        documents = []
        for match in results["result"]["hits"]:
            doc = Document(
                page_content=match["fields"].get("content", ""),
                metadata={
                    "score": match["score"],
                    "category": match["fields"].get("category", ""),
                    "id": match["id"]
                }
            )
            documents.append(doc)

        return documents

def create_retriever():
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(PINECONE_INDEX_NAME)

    return PineconeRetriever(
        index=index,
        top_k=TOP_K,
        namespace=PINECONE_NAMESPACE
    )