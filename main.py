import os
import logging
from typing import List, Optional
import certifi  # added: use certifi CA bundle for TLS verification
import urllib.parse  # added: parse and percent-encode credentials

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from pymongo import MongoClient, errors
from bson.objectid import ObjectId

# configure logger
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger("todo")

app = FastAPI(title="Todo API (Mongo Atlas connectivity test)")

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")

def _mask_uri(uri: str) -> str:
    # hide credentials if present (simple heuristic)
    try:
        if "//" in uri and "@" in uri:
            prefix, rest = uri.split("//", 1)
            _, host = rest.split("@", 1)
            return f"{prefix}//<redacted>@{host}"
    except Exception:
        pass
    return uri

def _mask_user_host(uri: str) -> str:
    try:
        p = urllib.parse.urlparse(uri)
        user = p.username or "<no-user>"
        host = p.hostname or "<no-host>"
        return f"{user}@{host}"
    except Exception:
        return "<masked>"

def _encode_credentials_if_needed(uri: str) -> str:
    """
    If URI contains credentials, percent-encode username/password and
    return a reconstructed URI. Fallback to a simple pattern match if urlparse fails.
    """
    p = urllib.parse.urlparse(uri)
    if p.username or p.password:
        user_enc = urllib.parse.quote(p.username or "", safe="")
        pw_enc = urllib.parse.quote(p.password or "", safe="")
        hostport = p.hostname or ""
        if p.port:
            hostport += f":{p.port}"
        netloc = f"{user_enc}:{pw_enc}@{hostport}"
        rebuilt = urllib.parse.urlunparse((p.scheme, netloc, p.path or "", p.params or "", p.query or "", p.fragment or ""))
        return rebuilt

    # Fallback: look for a simple user:pass@ pattern before the first '@'
    if "@" in uri and "://" in uri:
        try:
            scheme, rest = uri.split("://", 1)
            creds, hostrest = rest.split("@", 1)
            if ":" in creds:
                user, pw = creds.split(":", 1)
                user_enc = urllib.parse.quote(user, safe="")
                pw_enc = urllib.parse.quote(pw, safe="")
                new_rest = f"{user_enc}:{pw_enc}@{hostrest}"
                return f"{scheme}://{new_rest}"
        except Exception:
            pass

    return uri

# Create client factory that uses certifi CA bundle
def _make_client(uri: str, timeout_ms: int):
    return MongoClient(uri, tls=True, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=timeout_ms)

# Attempt to construct a client and ping MongoDB.
# On authentication failure, try retrying with percent-encoded credentials.
client = None
_client_timeout = int(os.environ.get("MONGO_CLIENT_TIMEOUT_MS", "10000"))
try:
    client = _make_client(MONGO_URI, _client_timeout)
    client.admin.command("ping")
    logger.info("Connected to MongoDB (%s)", _mask_user_host(MONGO_URI))
except Exception as exc:
    # Log the error (avoid logging secrets). If it's an auth error, try percent-encoding credentials and retry once.
    logger.exception("Failed to connect to MongoDB (%s): %s", _mask_user_host(MONGO_URI), exc)

    # Try a retry with encoded credentials if auth-like error
    try:
        encoded = _encode_credentials_if_needed(MONGO_URI)
        if encoded != MONGO_URI:
            logger.info("Retrying connection with percent-encoded credentials (masked: %s)", _mask_user_host(encoded))
            client = _make_client(encoded, max(_client_timeout, 10000))
            client.admin.command("ping")
            logger.info("Connected to MongoDB after encoding credentials. Update your MONGO_URI to use percent-encoded credentials.")
            # don't log the encoded URI or password
        else:
            logger.info("No credentials present to encode; connection failed for a different reason.")
    except Exception as exc2:
        logger.exception(
            "Retry with encoded credentials failed (%s). Check credentials, Atlas IP access list, and that MONGO_URI is correct.",
            exc2,
        )
        # leave client as-is (likely None or unusable); health endpoint will return proper error.

db = client.get_database("todo_db")
todos_col = db.get_collection("todos")


class TodoIn(BaseModel):
    title: str = Field(..., example="Buy milk")
    description: Optional[str] = Field(None, example="2 liters")
    done: bool = False


class TodoOut(TodoIn):
    id: str


def _serialize(todo: dict) -> TodoOut:
    return TodoOut(
        id=str(todo["_id"]),
        title=todo.get("title"),
        description=todo.get("description"),
        done=todo.get("done", False),
    )


@app.get("/health")
def health():
    """
    Health check that pings MongoDB to verify connectivity.
    Returns 200 when the MongoDB server responds to 'ping', otherwise 503.
    """
    try:
        client.admin.command("ping")
        return {"status": "ok", "mongo": "reachable"}
    except errors.PyMongoError as e:
        raise HTTPException(status_code=503, detail=f"mongo_unreachable: {str(e)}")


@app.post("/todos", response_model=TodoOut, status_code=201)
def create_todo(todo: TodoIn):
    payload = todo.dict()
    result = todos_col.insert_one(payload)
    created = todos_col.find_one({"_id": result.inserted_id})
    return _serialize(created)


@app.get("/todos", response_model=List[TodoOut])
def list_todos():
    docs = todos_col.find().sort("_id", -1)
    return [_serialize(d) for d in docs]


@app.get("/todos/{todo_id}", response_model=TodoOut)
def get_todo(todo_id: str):
    try:
        oid = ObjectId(todo_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid id")
    doc = todos_col.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="not found")
    return _serialize(doc)


@app.delete("/todos/{todo_id}", status_code=204)
def delete_todo(todo_id: str):
    try:
        oid = ObjectId(todo_id)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid id")
    result = todos_col.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="not found")
    return None
