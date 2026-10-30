import os
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ConfigurationError

_client = None
_db = None
_checked = False


def get_db():
    """Return the MongoDB database handle, or None if unavailable."""
    global _client, _db, _checked

    if _checked:
        return _db

    _checked = True

    uri = os.environ.get('MONGO_URI')

    if not uri:
        return None

    try:
        _client = MongoClient(uri, serverSelectionTimeoutMS=3000)
        _client.admin.command('ping')

        db_name = os.environ.get('MONGO_DB_NAME', 'mumbai_navigator')
        _db = _client[db_name]

        return _db

    except (ConnectionFailure, ConfigurationError) as e:
        print(f"[db] Could not connect to MongoDB ({e}). "
              f"Falling back to built-in map data.")
        _db = None
        return None


def is_connected():
    return get_db() is not None