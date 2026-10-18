import logging

from app.config import settings


def configure_logging() -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
    )
    # uvicorn's access log duplicates our request logging middleware.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
