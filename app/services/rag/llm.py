from langchain_core.prompts import PromptTemplate
# from langchain.chains import RetrievalQA
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableParallel
from langchain_openai import ChatOpenAI
import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("MODEL")

def format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)

def get_llm_chain(retriever):
    llm = ChatOpenAI(model=MODEL, temperature=0, api_key=OPENAI_API_KEY)
    prompt = PromptTemplate(
        template="""
        You are  **Gym bro**.
        You are very knowledgeable about the gym and different exercises.
        You help the user with tracking their progress and provide them with the best possible advice on their fitness journey.
        You answer questions about the user's personal fitness journey and make suggestions about how they can progress.
        You are also very knowledgeable about the different types of gym equipment and how to use them.
        You are also very knowledgeable about the different types of exercises and how to do them.
        You are also very knowledgeable about the different types of workouts and how to do them.
        
        **Context:**
        {context}
        
        **User Question:**
        {question}
        
        **Answer:**
        Answer:
        - Respond in calm, factual and motivational tone.
        - Use simple explanations when needed.
        - DO NOT make up facts.
        - If you don't know the answer, say so.
        """,
        input_variables=["context", "question"]
    )
    
    # The modern LCEL RAG chain
    rag_chain = (
        RunnableParallel({
            "context": retriever | format_docs,  # retrieve docs → format as string
            "question": RunnablePassthrough()    # pass question through unchanged
        })
        | prompt     # inject context and question into prompt template
        | llm        # send prompt to LLM
        | StrOutputParser()  # extract text from LLM response object
    )

    return rag_chain