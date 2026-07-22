import logging

def setup_logger(): 
    logger = logging.getLogger("gym-ai-api")
    logger.setLevel(logging.INFO)

    # Create console handler and set level to info
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # Add formatter to handler to format the log output
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    ))

    # Avoid duplicate handlers if the logger is re-imported to prevent multiple logs
    if not logger.hasHandlers():
        logger.addHandler(console_handler)

    # Return the logger for use in the application
    return logger

logger = setup_logger()

logger.info("RAG process started")
logger.debug("Debugging")
logger.error("Failed to load")
logger.critical("Critical message")