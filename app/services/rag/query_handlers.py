from app.logger import logger

def query_chain(chain, user_input:str):
    try:
        logger.debug(f"Running chain for user input: {user_input}")
        result = chain.invoke(user_input)
        # response={
        #     "response": result["result"],
        #     "sources": [
        #         doc.metadata.get("source", "")        # ✅ correct dict syntax
        #         for doc in result.get("source_documents", [])  # ✅ safe fallback
        #     ],
        # }
        response = {
            "response": result,            # ✅ LCEL returns plain string directly
            "sources": [],                 # sources not available in basic LCEL chain
        }
        logger.debug(f"Chain Response: {response}")
        return response
    except Exception as e:
        logger.exception(f"Error in query chain: {e}")
        return f"Error: {e}"