from app.logger import logger


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


async def stream_chain(chain, user_input: str, history=None):
    logger.debug(f"Streaming chain for user input: {user_input}")
    chain_input = {
        "question": user_input,
        "history": history or [],
    }

    async for chunk in chain.astream(chain_input):
        text = chunk if isinstance(chunk, str) else str(chunk)
        if text:
            yield text
