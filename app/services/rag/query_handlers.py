from app.logger import logger
from app.services.rag.agent import stream_agent as run_agent


async def stream_agent(db, user_id, user_input, history, retriever):

    logger.debug(f"Streaming agent for user input: {user_input} by user {user_id}")
    async for token in run_agent(db, user_id, user_input, history, retriever):
        if token:
            yield token

def query_chain(chain, user_input: str, history=None):
    try:
        logger.debug(f"Running chain for user input: {user_input}")
        result = chain.invoke({
            "question": user_input,
            "history": history or [],
        })
        response = {
            "response": result,
            "sources": [],
        }
        logger.debug(f"Chain Response: {response}")
        return response
    except Exception as e:
        logger.exception(f"Error in query chain: {e}")
        raise