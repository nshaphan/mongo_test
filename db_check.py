import os
import sys
import logging
import urllib.parse
from pymongo import MongoClient, errors
import certifi
from dotenv import load_dotenv

load_dotenv()  # optional for local .env

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("db_check")

MONGO_URI = os.environ.get("MONGO_URI")
if not MONGO_URI:
    print("MONGO_URI not set. Set MONGO_URI in env or create a .env file.")
    sys.exit(2)


def _mask_uri(uri: str) -> str:
    try:
        p = urllib.parse.urlparse(uri)
        user = p.username or "<no-user>"
        host = p.hostname or "<no-host>"
        return f"{user}@{host}"
    except Exception:
        # fallback simple mask
        if "@" in uri:
            left, right = uri.split("@", 1)
            return f"<redacted>@{right}"
        return "<masked>"


print("Detected (masked):", _mask_uri(MONGO_URI))
print("Attempting MongoDB connection (using certifi CA bundle)...")

try:
    client = MongoClient(MONGO_URI, tls=True, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=10000)
    client.admin.command("ping")
    print("SUCCESS: connected and pinged MongoDB.")
    sys.exit(0)
except errors.OperationFailure as op_err:
    # authentication / command errors
    print("AUTH/OPERATION FAILURE:", str(op_err))
    print("")
    print("Suggested checks:")
    print("- Verify the username and password are correct in your Atlas user.")
    print("- Reset the user's password in Atlas and paste the new connection string.")
    print("- If the password contains special characters, percent-encode them in the URI (e.g. use urllib.parse.quote).")
    print("- Ensure the user is created in the correct authentication DB and has appropriate roles.")
    print("- Confirm the cluster connection string you copied from Atlas is complete (SRV or standard).")
    sys.exit(3)
except errors.PyMongoError as e:
    print("Pymongo error:", str(e))
    print("")
    print("Suggested checks:")
    print("- Ensure Atlas IP Access List allows connections from this host (or 0.0.0.0/0 for quick test).")
    print("- Verify DNS/SRV resolution works (try `nslookup` on your host for the cluster hostnames).")
    print("- Check local OpenSSL / Python TLS support (TLS1.2+ required).")
    sys.exit(4)
except Exception as e:
    print("Unexpected error:", str(e))
    sys.exit(5)
