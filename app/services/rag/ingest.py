import os
import time
import glob
import uuid
from pathlib import Path
from dotenv import load_dotenv
from tqdm.auto import tqdm
from pinecone import Pinecone
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_ENV = os.getenv("PINECONE_ENV")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME")
DB_NAME = str(Path(__file__).parent.parent / "vector_db")
EXERCISE_KNOWLEDGE_BASE = str(Path(__file__).parent.parent / "knowledge-base" / "exercises")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL")

os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

#initialize pinecone instance
pc = Pinecone(api_key=PINECONE_API_KEY)

if not pc.has_index(PINECONE_INDEX_NAME):
    pc.create_index_for_model(
        name=PINECONE_INDEX_NAME,
        cloud="aws",
        region="us-east-1",
        embed={
            "model": EMBEDDING_MODEL,
            "field_map": {"text": "content"}
        }
    )
    while not pc.describe_index(PINECONE_INDEX_NAME).status.ready:
        time.sleep(1)
        
index = pc.Index(PINECONE_INDEX_NAME)

# Load, split and upsert knowledge base MD files
def fetch_documents():
    print("Fetching documents...")
    print(f"EXERCISE_KNOWLEDGE_BASE: {EXERCISE_KNOWLEDGE_BASE}")
    exercise_folders = glob.glob(str(Path(EXERCISE_KNOWLEDGE_BASE) / "*"))
    print(f"Found {len(exercise_folders)} exercise folders")
    documents = []
    for folder in exercise_folders:
        doc_type = os.path.basename(folder)
        loader = DirectoryLoader(
            folder, glob="**/*.md", loader_cls=TextLoader, loader_kwargs={"encoding": "utf-8"}
        )
        folder_docs = loader.load()
        for doc in folder_docs:
            doc.metadata["doc_type"] = doc_type
            documents.append(doc)
    print(f"Found {len(documents)} documents")
    return documents

def create_chunks(documents):
    print("Creating chunks...")
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=200)
    chunks = text_splitter.split_documents(documents)
    print(f"Created {len(chunks)} chunks")
    return chunks

def get_records(chunks):
    records = [
        {
            "_id": str(uuid.uuid4()),
            "content": chunk.page_content,
            "category": chunk.metadata["doc_type"],
        }
        for chunk in chunks
    ]
    
    # Split into batches of 96
    batch_size = 96
    record_batches = [records[i:i + batch_size] for i in range(0, len(records), batch_size)]
    print(f"Created {len(records)} records")
    return record_batches

def load_vectorstore():
    print("Loading vectorstore...")
    documents = fetch_documents()
    chunks = create_chunks(documents)
    record_batches = get_records(chunks)
    
    
    for i, batch in enumerate(record_batches):
        index.upsert_records(
            namespace=os.getenv("PINECONE_NAMESPACE"),
            records=batch
        )
        print(f"Upserted batch {i + 1} of {len(record_batches)}")
    
    print(f"Successfully upserted {len(record_batches)} record batches to Pinecone ✅")
    
if __name__ == "__main__":
    load_vectorstore()