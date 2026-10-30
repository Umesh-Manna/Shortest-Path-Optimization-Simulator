# How MongoDB Works in This Project

This document explains, in detail, how MongoDB is wired into the Mumbai Map Navigator's backend: what it stores, how the connection is established, how each request flows through it, and what happens when it isn't available at all.

---

## 1. The big picture

Before MongoDB was added, all location and road data lived in two hardcoded Python dictionaries inside `mumbai_map_navigator.py`. That meant:

- Adding a new location required editing code and redeploying
- There was no way to know which routes people actually searched for
- Nothing persisted between app restarts beyond what was typed into the source file

MongoDB replaces that hardcoded data with three collections in a database, **without removing the fallback** — if MongoDB isn't configured or isn't reachable, the app automatically uses the original hardcoded data instead. Nothing breaks either way.

```
┌─────────────┐      HTTP        ┌─────────────┐     pymongo      ┌──────────────┐
│   Browser   │ ───────────────▶ │  Flask app  │ ────────────────▶│   MongoDB    │
│ (index.html)│ ◀─────────────── │  (main.py)  │ ◀──────────────── │ 3 collections│
└─────────────┘      JSON        └─────────────┘     documents     └──────────────┘
                                        │
                                        │ falls back if Mongo is
                                        │ unset/unreachable
                                        ▼
                                 hardcoded dict
                                 (_DEFAULT_LOCATIONS,
                                  _DEFAULT_EDGES)
```

---

## 2. The three collections

MongoDB is schemaless, but in practice this app treats each collection as having a consistent shape:

### `locations`
One document per place.

```json
{
  "name": "Bandra",
  "description": "Upscale suburban area known for shopping and seafront",
  "lat": 19.0596,
  "lon": 72.8295
}
```

`name` has a **unique index** (created in `seed_db.py`), so you can't accidentally insert the same location twice.

### `edges`
One document per road connection. Roads are stored in a **single direction only** — the app treats every edge as bidirectional in memory (see §5).

```json
{
  "from": "Bandra",
  "to": "Dadar",
  "distance": 7,
  "time": 30,
  "fuel": 1.7
}
```

### `searches`
One document per completed route search — this is the collection that didn't exist before MongoDB. It's what powers the "Popular routes" feature.

```json
{
  "start": "Bandra",
  "end": "Dadar",
  "distance": 7,
  "time": 30,
  "fuel": 1.7,
  "timestamp": "2026-09-22T10:15:32.000Z"
}
```

`timestamp` has an index (created in `seed_db.py`) so future features (e.g. "routes searched this week") can query it efficiently.

---

## 3. Establishing the connection — `db.py`

This is the only file that talks to MongoDB directly. Everything else goes through it.

```python
def get_db():
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
        print(f"[db] Could not connect to MongoDB ({e}). Falling back...")
        _db = None
        return None
```

Key details:

- **Reads `MONGO_URI` from the environment.** Nothing is hardcoded — this is what makes it work identically for a local MongoDB, a Docker container, or a MongoDB Atlas cluster. If the variable isn't set, `get_db()` returns `None` immediately, without even trying to connect.
- **`serverSelectionTimeoutMS=3000`** — if a URI *is* set but the server can't be reached, pymongo fails fast (3 seconds) instead of hanging the app on startup.
- **`.admin.command('ping')`** — `MongoClient(...)` alone doesn't actually open a connection (pymongo connects lazily). This explicit ping forces a real round-trip so we know immediately whether the database is actually reachable, rather than finding out later when the first query mysteriously fails.
- **Caches the result.** `_checked` is a module-level flag: `get_db()` only tries to connect once per process. Every subsequent call returns the cached `_db` (which is either a working database handle or `None`) instead of reconnecting every time.
- **`MONGO_DB_NAME`** (optional, defaults to `mumbai_navigator`) lets you point at a different database name without touching code — useful for separating a dev database from production.

---

## 4. How the navigator uses it — `mumbai_map_navigator.py`

`MumbaiMapNavigator.__init__` is where the fallback decision actually happens:

```python
def __init__(self):
    self.db = get_db()
    self.using_mongo = self.db is not None

    if self.using_mongo:
        self.locations, self.mumbai_map = self._load_from_mongo()
    else:
        self.locations = _DEFAULT_LOCATIONS
        self.mumbai_map = _DEFAULT_EDGES

    self.sorted_locations = sorted(self.locations.keys())
```

`self.using_mongo` is checked everywhere else in the class, so the rest of the code never has to guess whether MongoDB is active — it just asks this one flag.

### Loading data from MongoDB — `_load_from_mongo()`

```python
def _load_from_mongo(self):
    locations = {
        doc['name']: Location(doc['name'], doc['description'], doc['lat'], doc['lon'])
        for doc in self.db.locations.find()
    }

    graph = {name: {} for name in locations}
    for edge in self.db.edges.find():
        a, b = edge['from'], edge['to']
        weight = (edge['distance'], edge['time'], edge['fuel'])
        if a in graph:
            graph[a][b] = weight
        if b in graph:
            graph[b][a] = weight   # roads are bidirectional

    if not locations:
        return _DEFAULT_LOCATIONS, _DEFAULT_EDGES

    return locations, graph
```

What's happening here:

1. `self.db.locations.find()` pulls every document from the `locations` collection with no filter — this is a full collection scan, which is fine at this scale (a few dozen locations) but would want a filter or projection at larger scale.
2. Each MongoDB document is converted into a `Location` object — this is the adapter layer between "what MongoDB stores" and "what the rest of the app (which was written before MongoDB existed) expects."
3. For `edges`, each document is stored **once** (e.g. `Bandra → Dadar`), but the in-memory graph adds it **both ways** (`Bandra → Dadar` and `Dadar → Bandra`). This is a deliberate simplification: it halves the number of documents you need to seed/maintain, since real roads are two-way anyway.
4. **The empty-database safeguard**: if MongoDB connects successfully but the collections are empty (e.g. you set `MONGO_URI` but forgot to run `seed_db.py`), it falls back to the hardcoded data rather than serving an app with zero locations. This is the same fallback used when MongoDB is completely unreachable — just triggered by a different condition.

After this runs, `self.locations` and `self.mumbai_map` look **structurally identical** whether they came from MongoDB or from the hardcoded dictionaries. That's why `dijkstra()`, `calculate_trip_details()`, `get_location_info()`, and `create_map_visualization()` didn't need to change at all — they only ever operate on `self.locations` / `self.mumbai_map`, and have no idea whether MongoDB exists.

### Writing to MongoDB — two methods

**`log_search()`** — called after every successful pathfind (see §5):

```python
def log_search(self, start, end, distance, time, fuel):
    if not self.using_mongo:
        return
    self.db.searches.insert_one({
        'start': start, 'end': end,
        'distance': distance, 'time': time, 'fuel': fuel,
        'timestamp': datetime.now(timezone.utc)
    })
```

This is a no-op when MongoDB isn't configured — it checks `self.using_mongo` and returns immediately, so `main.py` can call it unconditionally without needing its own `if` check.

**`add_location()`** — the "add a place without editing code" feature:

```python
def add_location(self, name, description, lat, lon, connections=None):
    if not self.using_mongo:
        raise RuntimeError('Adding locations requires MongoDB. Set MONGO_URI.')

    self.db.locations.update_one(
        {'name': name},
        {'$set': {'name': name, 'description': description, 'lat': lat, 'lon': lon}},
        upsert=True)

    for conn in (connections or []):
        self.db.edges.insert_one({
            'from': name, 'to': conn['to'],
            'distance': conn['distance'], 'time': conn['time'], 'fuel': conn['fuel']
        })

    self.locations, self.mumbai_map = self._load_from_mongo()
    self.sorted_locations = sorted(self.locations.keys())
```

Two MongoDB techniques worth calling out:

- **`update_one(..., upsert=True)`** — "update this location if it exists, insert it if it doesn't." This makes the operation idempotent: calling `add_location('Worli', ...)` twice updates the same document rather than creating a duplicate.
- **Reloading after writing** (`self._load_from_mongo()` again at the end) — this refreshes the in-memory graph immediately, so the very next `/find_path` request in the same running app can already route through the newly added location. Without this, you'd have to restart the Flask process to see the change.

Unlike `log_search()`, this one **raises an exception** rather than silently no-oping when MongoDB isn't available — because unlike logging a search (a nice-to-have), adding a location that can't actually be persisted anywhere would be a silent failure the caller needs to know about.

### Reading aggregated data — `get_popular_routes()`

```python
def get_popular_routes(self, limit=5):
    if not self.using_mongo:
        return []
    pipeline = [
        {'$group': {'_id': {'start': '$start', 'end': '$end'}, 'count': {'$sum': 1}}},
        {'$sort': {'count': -1}},
        {'$limit': limit}
    ]
    return [
        {'start': doc['_id']['start'], 'end': doc['_id']['end'], 'count': doc['count']}
        for doc in self.db.searches.aggregate(pipeline)
    ]
```

This uses MongoDB's **aggregation pipeline** — a sequence of stages each transforming the data:

1. **`$group`** — collapses every `searches` document into one group per unique `(start, end)` pair, counting how many documents fall into each group. This is the MongoDB equivalent of `SELECT start, end, COUNT(*) FROM searches GROUP BY start, end` in SQL.
2. **`$sort`** — orders the groups by `count` descending, so the most-searched pair comes first.
3. **`$limit`** — keeps only the top N (default 5).

This computation happens entirely inside MongoDB, not in Python — the database does the grouping and sorting, and only the final top-5 result travels back over the network.

---

## 5. Request-by-request walkthrough

### `POST /find_path`

```
Browser                Flask (main.py)              Navigator                    MongoDB
   │  start, end             │                            │                          │
   ├─────────────────────────▶                            │                          │
   │                         │  find_location() x2         │                          │
   │                         ├───────────────────────────▶ │                          │
   │                         │                            │  binary search over       │
   │                         │                            │  self.sorted_locations    │
   │                         │                            │  (already in memory,      │
   │                         │                            │   no DB call here)        │
   │                         │  dijkstra(start, end)        │                          │
   │                         ├───────────────────────────▶ │                          │
   │                         │                            │  runs over self.mumbai_map│
   │                         │                            │  (already in memory)      │
   │                         │  log_search(...)             │                          │
   │                         ├───────────────────────────▶ │  insert_one()            │
   │                         │                            ├─────────────────────────▶ │
   │  JSON result             │                            │                          │
   │◀─────────────────────────┤                            │                          │
```

Important detail: **pathfinding itself never touches MongoDB.** The graph was already loaded into `self.locations` / `self.mumbai_map` once, at startup (or the last time `add_location()` ran). `find_location()` and `dijkstra()` operate purely on that in-memory copy — this is why the app stays fast even with MongoDB in the loop: MongoDB is only written to (via `log_search`) after the path is already found, and that write doesn't block the response from completing (Flask waits for it, but it's a single fast `insert_one`).

### `GET /popular_routes`

```
Browser                Flask                        Navigator                  MongoDB
   │  GET /popular_routes    │                            │                          │
   ├─────────────────────────▶                            │                          │
   │                         │  get_popular_routes(5)       │                          │
   │                         ├───────────────────────────▶ │  aggregate(pipeline)     │
   │                         │                            ├─────────────────────────▶ │
   │                         │                            │◀─────────────────────────┤
   │  JSON list (or [])       │                            │                          │
   │◀─────────────────────────┤                            │                          │
```

Called once when the page loads (`$.get('/popular_routes', ...)` in `index.html`). If MongoDB isn't configured, this returns `[]` and the front end simply doesn't render the "Popular routes" chip row — no error, no empty box.

### `POST /add_location`

```
Browser                Flask                        Navigator                  MongoDB
   │  name, lat, lon, ...    │                            │                          │
   ├─────────────────────────▶                            │                          │
   │                         │  add_location(...)           │                          │
   │                         ├───────────────────────────▶ │  update_one(upsert=True) │
   │                         │                            ├─────────────────────────▶ │
   │                         │                            │  insert_one() per edge   │
   │                         │                            ├─────────────────────────▶ │
   │                         │                            │  _load_from_mongo()       │
   │                         │                            │  (refresh in-memory graph)│
   │                         │                            │  find() x2               │
   │                         │                            ├─────────────────────────▶ │
   │  JSON: success + list    │                            │                          │
   │◀─────────────────────────┤                            │                          │
```

This is the only endpoint that **writes structural data** (as opposed to just logging). If `MONGO_URI` isn't set, `main.py` catches the `RuntimeError` from `add_location()` and returns a `400` with an explanatory error instead of crashing.

---

## 6. Seeding — `seed_db.py`

This script is what turns an empty MongoDB database into a working one. It's meant to be run once (or re-run any time you want to reset back to the original 10 locations):

```python
db.locations.delete_many({})
db.edges.delete_many({})
db.locations.insert_many(location_docs)
db.edges.insert_many(edge_docs)
db.locations.create_index('name', unique=True)
db.searches.create_index('timestamp')
```

- `delete_many({})` with an empty filter matches every document — this clears both collections before reinserting, which is what makes the script **idempotent** (safe to run multiple times without producing duplicates).
- `insert_many()` inserts every document in a single round-trip, rather than looping with `insert_one()` per document.
- The indexes are created **after** seeding: `name` unique on `locations` (prevents future duplicate inserts, e.g. from a buggy `add_location()` call), and `timestamp` on `searches` (for efficient future time-based queries, even though nothing currently uses it).

`db.searches` isn't explicitly created here — MongoDB creates collections automatically the first time a document is inserted into them (which happens the first time `log_search()` runs), so there's nothing to seed for it beyond the index.

---

## 7. Why the fallback design matters

Three separate mechanisms combine to make MongoDB **strictly additive** rather than a hard dependency:

| Situation | What happens |
|---|---|
| `MONGO_URI` not set | `get_db()` returns `None` immediately, no connection attempt |
| `MONGO_URI` set but unreachable | `MongoClient(...).admin.command('ping')` raises `ConnectionFailure`, caught, `get_db()` returns `None` |
| MongoDB reachable but empty (not seeded) | `_load_from_mongo()` sees zero locations and returns the hardcoded defaults instead |

In every one of these cases, `self.using_mongo` ends up `False`, and every MongoDB-dependent feature (`log_search`, `get_popular_routes`, `add_location`) degrades gracefully — either doing nothing, returning an empty result, or raising a clear, catchable error — instead of throwing an unhandled exception that would crash a request.

---

## 8. Summary of what MongoDB adds

| Feature | Existed before MongoDB? | How MongoDB enables it |
|---|---|---|
| Location/road data | Yes (hardcoded) | Now editable data instead of code |
| Adding new locations | No (required a code change + redeploy) | `add_location()` + `/add_location` endpoint |
| Popular routes | No | `searches` collection + aggregation pipeline |
| Search history | No | Every `/find_path` call is logged via `log_search()` |
| Works with zero setup | Yes | Still true — fallback to hardcoded data is preserved |
