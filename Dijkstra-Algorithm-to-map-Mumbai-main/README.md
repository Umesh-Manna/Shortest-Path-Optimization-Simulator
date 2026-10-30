# Mumbai Map Navigator

A Flask web app that finds routes between places in Mumbai using **Dijkstra's algorithm**, with a choice of what to optimize for (distance, time, or fuel), up to three ranked alternate routes per search, and results drawn on an interactive map.

You pick a start and end location, choose what to optimize for, hit **Find Path**, and the app returns the route(s), totals, and a map with the path drawn on it.

---

## What the website actually does

1. **You choose two locations and an optimization goal.** The homepage (`/`) loads the known Mumbai locations into the "Start"/"End" dropdowns, plus a toggle for **Shortest distance**, **Fastest time**, or **Least fuel**. There's a swap button to flip start/end.
2. **You click "Find Path."** This sends the start, end, and chosen metric to the server via `/find_path`.
3. **The server finds the shortest path** — and up to two ranked alternates. `mumbai_map_navigator.py` models Mumbai as a graph (locations as nodes, roads as weighted edges carrying distance/time/fuel) and runs Dijkstra's algorithm weighted by whichever metric you chose. A Yen's-algorithm-based search (`k_shortest_paths`) then finds additional loopless alternate routes, ranked by the same metric.
4. **The server builds a map for each route.** It plots markers for every stop and, via the `folium` library, draws the path — using real road geometry from the OSRM routing service when reachable, falling back to a straight-line path if not — then sends the map back as embeddable HTML.
5. **The page displays the result:** the route, its real distance/time/fuel totals, and the map. If alternates exist, they appear as tabs — switching tabs swaps the stats and map instantly, with no extra server call.
6. **If a location isn't recognized** (e.g. a typo), the app uses fuzzy string matching to suggest close matches instead of just failing silently.

## Tech stack

| Piece | Role |
|---|---|
| **Flask** (`main.py`) | Web server; serves the page, validates input, and exposes the API endpoints |
| **`mumbai_map_navigator.py`** | Core logic: location data, the road-network graph, multi-criteria Dijkstra, k-shortest-paths, fuzzy search, map generation |
| **`routing.py`** | Fetches real road-following geometry from OSRM; falls back to a straight line if unreachable |
| **`db.py` / `seed_db.py`** | Optional MongoDB layer — see [MONGODB.md](./MONGODB.md) for a full breakdown |
| **`folium`** | Generates the interactive Leaflet-based map embedded in the results |
| **HTML/CSS/jQuery** (`templates/index.html`) | Front end — dropdowns, metric toggle, route tabs, and rendering the JSON response |

## Project structure

```
├── main.py                     # Flask routes + input validation
├── mumbai_map_navigator.py     # Graph data, multi-criteria Dijkstra, k-shortest-paths, map generation
├── routing.py                  # OSRM road-geometry lookup (with straight-line fallback)
├── db.py                       # MongoDB connection helper (optional)
├── seed_db.py                  # One-time MongoDB seed script (optional)
├── templates/
│   └── index.html              # Front-end UI
├── tests/
│   ├── test_navigator.py       # Routing logic tests
│   └── test_app.py             # Flask endpoint / validation tests
├── .github/workflows/tests.yml # CI: runs the test suite on every push/PR
├── requirements.txt
├── Dockerfile
├── docker-compose.yml          # App + MongoDB, for local dev
└── README.md
```

## Running it locally

```bash
pip install -r requirements.txt
python main.py
```

Then open **http://localhost:8080** in your browser.

### With Docker

```bash
docker compose up --build
```

This starts the app and a local MongoDB together. Without MongoDB configured, the app runs fine on its own too — `docker build . && docker run -p 8080:8080 <image>` works standalone.

## Running the tests

```bash
python -m unittest discover -s tests -v
```

Tests run against the app's built-in fallback data, so no MongoDB setup is needed — the same suite runs in CI (`.github/workflows/tests.yml`) on every push and pull request. Coverage includes: routing correctness across all three metrics, k-shortest-paths behavior (uniqueness, ranking, non-mutation of the graph), Flask endpoint responses, and `/add_location` input validation.

## API endpoints

- `GET /` — renders the main page with the location dropdowns
- `POST /find_path` — takes `start`, `end`, and optional `metric` (`distance` | `time` | `fuel`, defaults to `distance`); returns the best route plus up to two alternates, each with distance/time/fuel and a rendered map (or an error with suggestions for unrecognized locations)
- `POST /location_info` — takes a `name` field, returns a description of that location and its direct connections
- `GET /popular_routes` — most-searched start/end pairs (empty list if MongoDB isn't configured)
- `POST /add_location` — add a location and its road connections; validates name/coordinates/connections before touching the database (see below); requires MongoDB

## Notes on the data

The current map covers 10 well-known Mumbai locations (e.g. Chhatrapati Shivaji Terminus, Marine Drive, Bandra, Juhu, Andheri) with hand-entered distances, times, and fuel estimates between connected points — it's a demonstration graph, not live traffic or mapping data.

## MongoDB support (optional)

The app can optionally run on MongoDB instead of the hardcoded map data. This unlocks two things a plain dictionary can't:

- **Adding locations/roads without touching code** — via the `/add_location` endpoint
- **A "Popular routes" list** — every successful search is logged, and the homepage shows the most-searched routes as quick-pick chips

If MongoDB isn't configured, none of this changes: the app silently falls back to the original hardcoded map, and the popular-routes section just stays hidden.

### Setup

1. Have a MongoDB instance available — either [local](https://www.mongodb.com/docs/manual/installation/) or a free [MongoDB Atlas](https://www.mongodb.com/atlas) cluster.
2. Set the connection string:
   ```bash
   export MONGO_URI="mongodb://localhost:27017"
   # or an Atlas URI: mongodb+srv://user:pass@cluster.mongodb.net
   ```
3. Seed the database with the existing location/road data (one-time):
   ```bash
   python seed_db.py
   ```
4. Run the app as usual:
   ```bash
   python main.py
   ```

### What's stored where

| Collection | Contents |
|---|---|
| `locations` | Name, description, latitude, longitude |
| `edges` | Road connections: `from`, `to`, distance (km), time (min), fuel (L) |
| `searches` | Every completed search: start, end, totals, timestamp — powers "Popular routes" |

### New/changed files

- `db.py` — MongoDB connection helper (reads `MONGO_URI`, returns `None` gracefully if unset/unreachable)
- `seed_db.py` — one-time script to load the existing map data into MongoDB
- `mumbai_map_navigator.py` — now loads from MongoDB when available, otherwise falls back to the built-in data; adds `log_search()`, `get_popular_routes()`, `add_location()`
- `main.py` — logs each search, adds `GET /popular_routes` and `POST /add_location`

### Adding a location via the API

```bash
curl -X POST http://localhost:8080/add_location \
  -H "Content-Type: application/json" \
  -d '{
        "name": "Worli",
        "description": "Coastal suburb, home to the Worli Sea Face",
        "lat": 19.0176, "lon": 72.8161,
        "connections": [
          {"to": "Mahalaxmi", "distance": 4, "time": 15, "fuel": 1.0}
        ]
      }'
```

### Ideas to take this further

- Add a small admin form in the UI for `/add_location` instead of curl
- Store user-submitted feedback per route (e.g. "traffic was worse than shown")
- Cache `/find_path` results in Mongo for repeat start/end pairs
- Add TTL-indexed session data if you introduce user accounts later

## Multi-criteria routing & alternate routes

`/find_path` accepts a `metric` field — `distance`, `time`, or `fuel` — which changes what Dijkstra's algorithm optimizes for. This matters because the "shortest" route isn't always the same route depending on what you care about: a route with fewer km might involve slower roads, and vice versa.

On top of the single best route, `mumbai_map_navigator.py` also computes **up to two loopless alternates** using a Yen's-algorithm-style search (`k_shortest_paths`): it finds the best route, then systematically removes pieces of it and re-runs Dijkstra to find the next-best distinct route, repeating until it has k candidates or runs out of alternatives. Every candidate is explored on a deep copy of the graph, so the real graph is never mutated.

Each route in the response includes its **real** distance/time/fuel totals — independent of which metric was used to rank it — so you always see the honest cost of every option, not just the one you optimized for.

## Input validation on `/add_location`

Adding a location now goes through real validation before anything touches MongoDB:

- `name` — required, non-empty, ≤100 characters
- `description` — optional, ≤500 characters
- `lat`/`lon` — required numbers, and must fall within Mumbai's approximate bounding box (lat 18.80–19.35, lon 72.70–73.05) — this catches typos like swapped coordinates or a location entered in the wrong city
- `connections` (optional) — each must reference an existing location (no dangling roads to places that don't exist) and can't connect a location to itself; `distance`, `time`, and `fuel` must all be positive numbers

Any failure returns a `400` with a specific error message (e.g. `"lat must be between 18.8 and 19.35 (Mumbai region)"`) rather than a generic failure or a silently corrupted database entry.
