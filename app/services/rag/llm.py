from operator import itemgetter

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableParallel
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import os

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("MODEL")


def format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)


def get_llm_chain(retriever):
    llm = ChatOpenAI(
        model=MODEL,
        temperature=0,
        api_key=OPENAI_API_KEY,
        streaming=True,
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", """
        You are **Gym Bro AI**, a knowledgeable and motivational fitness coach.
        You help the user track their progress and provide the best possible advice on their fitness journey.
        You are knowledgeable about gym equipment, exercises, workout programs, and training principles.

        Use the following context from the fitness knowledge base to answer the user's question.

        **Context:**
        {context}

        **Guidelines:**
        - Respond in a calm, factual and motivational tone
        - Use simple explanations when needed
        - DO NOT make up facts
        - If you don't know the answer, say so honestly
        - Keep responses concise and to the point
        """),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{question}"),
    ])

    return (
        RunnableParallel({
            "context": itemgetter("question") | retriever | format_docs,
            "question": itemgetter("question"),
            "history": itemgetter("history"),
        })
        | prompt
        | llm
        | StrOutputParser()
    )
