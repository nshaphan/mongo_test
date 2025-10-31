import os
# add dotenv import and load before anything else that reads env vars
from dotenv import load_dotenv
load_dotenv()  # loads .env from project root if present

import logging
import uvicorn

# configure logging before importing app so main.py startup logs are visible
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger("todo.server")

def _mask_uri(uri: str) -> str:
    try:
        if "//" in uri and "@" in uri:
            prefix, rest = uri.split("//", 1)
            _, host = rest.split("@", 1)
            return f"{prefix}//<redacted>@{host}"
    except Exception:
        pass
    return uri

# log which MONGO_URI this process sees (masked)
logger.info("MONGO_URI detected: %s", _mask_uri(os.environ.get("MONGO_URI", "not-set")))

# Import the FastAPI app object from main.py (main.py will now emit connection logs)
from main import app  # main.py already defines `app`

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    logger.info("Starting server on 0.0.0.0:%s (log_level=%s)", port, LOG_LEVEL)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level=LOG_LEVEL.lower())
