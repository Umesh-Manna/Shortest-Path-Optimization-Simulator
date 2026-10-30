"""
Seeds MongoDB with the Mumbai Map Navigator's location and road data.

Run this once after setting MONGO_URI:

    export MONGO_URI="mongodb://localhost:27017"
    python seed_db.py

It populates two collections:
    - locations: one document per place (name, description, lat, lon)
    - edges: one document per road connection (from, to, distance, time, fuel)

Safe to re-run: it clears and re-inserts both collections each time.
"""

import os
import sys
from db import get_db

# The original hardcoded dataset — used as the seed source.
LOCATIONS = {
    'Chhatrapati Shivaji Terminus': {
        'description': 'Historic railway station and UNESCO World Heritage Site',
        'lat': 18.9398, 'lon': 72.8355
    },
    'Churchgate': {
        'description': 'Major railway terminus in South Mumbai',
        'lat': 18.9322, 'lon': 72.8264
    },
    'Marine Drive': {
        'description': 'Scenic 3.6-kilometer-long boulevard along the coast',
        'lat': 18.9438, 'lon': 72.8231
    },
    'Nariman Point': {
        'description': 'Central business district with modern skyscrapers',
        'lat': 18.9256, 'lon': 72.8242
    },
    'Byculla': {
        'description': 'Residential and commercial area with the famous Byculla Zoo',
        'lat': 18.9791, 'lon': 72.8304
    },
    'Dadar': {
        'description': 'Central Mumbai hub known for its flower market',
        'lat': 19.0178, 'lon': 72.8478
    },
    'Bandra': {
        'description': 'Upscale suburban area known for shopping and seafront',
        'lat': 19.0596, 'lon': 72.8295
    },
    'Juhu': {
        'description': 'Upmarket neighborhood famous for Juhu Beach',
        'lat': 19.0883, 'lon': 72.8263
    },
    'Andheri': {
        'description': 'Major residential and commercial suburb',
        'lat': 19.1136, 'lon': 72.8697
    },
    'Mahalaxmi': {
        'description': 'Home to Mahalaxmi Temple and Racecourse',
        'lat': 18.9825, 'lon': 72.8122
    },
}

# (from, to, distance_km, time_min, fuel_l) — one direction only,
# the app treats roads as bidirectional.
EDGES = [
    ('Chhatrapati Shivaji Terminus', 'Churchgate', 2, 10, 0.5),
    ('Chhatrapati Shivaji Terminus', 'Byculla', 5, 20, 1.2),
    ('Chhatrapati Shivaji Terminus', 'Mahalaxmi', 7, 25, 1.7),
    ('Churchgate', 'Marine Drive', 1, 5, 0.3),
    ('Marine Drive', 'Nariman Point', 3, 12, 0.7),
    ('Nariman Point', 'Byculla', 7, 28, 1.7),
    ('Byculla', 'Dadar', 6, 25, 1.5),
    ('Dadar', 'Bandra', 7, 30, 1.7),
    ('Bandra', 'Juhu', 5, 20, 1.2),
    ('Juhu', 'Andheri', 4, 18, 1.0),
]


def seed():
    db = get_db()
    if db is None:
        print("MONGO_URI is not set (or the connection failed). "
              "Set it and try again, e.g.:\n"
              '  export MONGO_URI="mongodb://localhost:27017"')
        sys.exit(1)

    db.locations.delete_many({})
    db.edges.delete_many({})

    location_docs = [
        {'name': name, **info} for name, info in LOCATIONS.items()
    ]
    db.locations.insert_many(location_docs)

    edge_docs = [
        {'from': a, 'to': b, 'distance': d, 'time': t, 'fuel': f}
        for (a, b, d, t, f) in EDGES
    ]
    db.edges.insert_many(edge_docs)

    db.locations.create_index('name', unique=True)
    db.searches.create_index('timestamp')

    print(f"Seeded {len(location_docs)} locations and "
          f"{len(edge_docs)} roads into MongoDB "
          f"({os.environ.get('shortest_path', 'mumbai_navigator')}).")


if __name__ == '__main__':
    seed()
