import copy
import heapq
from datetime import datetime, timezone
from difflib import get_close_matches

import folium

from db import get_db
from routing import get_route_geometry

# Which tuple index each optimization metric reads from an edge's
# (distance, time, fuel) weight.
METRIC_INDEX = {'distance': 0, 'time': 1, 'fuel': 2}


class Location:

    def __init__(self, name, description, lat, lon):
        self.name = name
        self.description = description
        self.lat = lat
        self.lon = lon


# Built-in fallback data, used only when no MongoDB is configured/reachable.
_DEFAULT_LOCATIONS = {
    'Chhatrapati Shivaji Terminus':
    Location('Chhatrapati Shivaji Terminus',
             'Historic railway station and UNESCO World Heritage Site',
             18.9398, 72.8355),
    'Churchgate':
    Location('Churchgate', 'Major railway terminus in South Mumbai',
             18.9322, 72.8264),
    'Marine Drive':
    Location('Marine Drive',
             'Scenic 3.6-kilometer-long boulevard along the coast',
             18.9438, 72.8231),
    'Nariman Point':
    Location('Nariman Point',
             'Central business district with modern skyscrapers',
             18.9256, 72.8242),
    'Byculla':
    Location('Byculla',
             'Residential and commercial area with the famous Byculla Zoo',
             18.9791, 72.8304),
    'Dadar':
    Location('Dadar', 'Central Mumbai hub known for its flower market',
             19.0178, 72.8478),
    'Bandra':
    Location('Bandra',
             'Upscale suburban area known for shopping and seafront',
             19.0596, 72.8295),
    'Juhu':
    Location('Juhu', 'Upmarket neighborhood famous for Juhu Beach',
             19.0883, 72.8263),
    'Andheri':
    Location('Andheri', 'Major residential and commercial suburb',
             19.1136, 72.8697),
    'Mahalaxmi':
    Location('Mahalaxmi', 'Home to Mahalaxmi Temple and Racecourse',
             18.9825, 72.8122),
}

_DEFAULT_EDGES = {
    'Chhatrapati Shivaji Terminus': {
        'Churchgate': (2, 10, 0.5),
        'Byculla': (5, 20, 1.2),
        'Mahalaxmi': (7, 25, 1.7)
    },
    'Churchgate': {
        'Chhatrapati Shivaji Terminus': (2, 10, 0.5),
        'Marine Drive': (1, 5, 0.3),
    },
    'Marine Drive': {
        'Churchgate': (1, 5, 0.3),
        'Nariman Point': (3, 12, 0.7),
    },
    'Nariman Point': {
        'Marine Drive': (3, 12, 0.7),
        'Byculla': (7, 28, 1.7),
    },
    'Byculla': {
        'Chhatrapati Shivaji Terminus': (5, 20, 1.2),
        'Nariman Point': (7, 28, 1.7),
        'Dadar': (6, 25, 1.5),
    },
    'Dadar': {
        'Byculla': (6, 25, 1.5),
        'Bandra': (7, 30, 1.7),
    },
    'Bandra': {
        'Dadar': (7, 30, 1.7),
        'Juhu': (5, 20, 1.2),
    },
    'Juhu': {
        'Bandra': (5, 20, 1.2),
        'Andheri': (4, 18, 1.0),
    },
    'Andheri': {
        'Juhu': (4, 18, 1.0),
    },
    'Mahalaxmi': {
        'Chhatrapati Shivaji Terminus': (7, 25, 1.7),
    },
}


class MumbaiMapNavigator:

    def __init__(self):
        self.db = get_db()
        self.using_mongo = self.db is not None

        if self.using_mongo:
            self.locations, self.mumbai_map = self._load_from_mongo()
        else:
            self.locations = _DEFAULT_LOCATIONS
            self.mumbai_map = _DEFAULT_EDGES

        self.sorted_locations = sorted(self.locations.keys())

    # ---------- data loading ----------

    def _load_from_mongo(self):
        locations = {
            doc['name']: Location(doc['name'], doc['description'],
                                   doc['lat'], doc['lon'])
            for doc in self.db.locations.find()
        }

        graph = {name: {} for name in locations}
        for edge in self.db.edges.find():
            a, b = edge['from'], edge['to']
            weight = (edge['distance'], edge['time'], edge['fuel'])
            if a in graph:
                graph[a][b] = weight
            if b in graph:
                graph[b][a] = weight  # roads are bidirectional

        # If Mongo is reachable but empty, fall back so the app still works.
        if not locations:
            return _DEFAULT_LOCATIONS, _DEFAULT_EDGES

        return locations, graph

    # ---------- lookup ----------

    def binary_search(self, target):
        left, right = 0, len(self.sorted_locations) - 1
        while left <= right:
            mid = (left + right) // 2
            if self.sorted_locations[mid] == target:
                return mid
            elif self.sorted_locations[mid] < target:
                left = mid + 1
            else:
                right = mid - 1
        return -1

    def find_location(self, name):
        index = self.binary_search(name)
        if index != -1:
            return self.sorted_locations[index]
        return None

    def fuzzy_search(self, name, cutoff=0.6):
        matches = get_close_matches(name,
                                     self.sorted_locations,
                                     n=3,
                                     cutoff=cutoff)
        return matches

    # ---------- map + pathfinding ----------

    def create_map_visualization(self, path):
        map_center = [18.9667, 72.8333]  # Approximate center of Mumbai
        m = folium.Map(location=map_center, zoom_start=12)

        waypoints = [(self.locations[loc].lat, self.locations[loc].lon)
                     for loc in path]

        # Pins: green for the start, red for the end, blue for stops in between —
        # mirrors how Google Maps marks a route.
        for i, location in enumerate(path):
            if i == 0:
                icon = folium.Icon(color='green', icon='play')
            elif i == len(path) - 1:
                icon = folium.Icon(color='red', icon='stop')
            else:
                icon = folium.Icon(color='blue', icon='circle', prefix='fa')
            folium.Marker(
                [self.locations[location].lat, self.locations[location].lon],
                popup=location,
                icon=icon).add_to(m)

        # Try to get the real road-following route from OSRM. Falls back to
        # a straight line between waypoints if the routing service can't be
        # reached (e.g. no network) so the map still renders either way.
        route_points = get_route_geometry(waypoints)

        if route_points:
            folium.PolyLine(route_points, color="#4f7df3", weight=5,
                             opacity=0.85).add_to(m)
        else:
            folium.PolyLine(waypoints, color="#4f7df3", weight=4,
                             opacity=0.6, dash_array='8,8').add_to(m)

        if len(waypoints) > 1:
            m.fit_bounds(waypoints)

        return m._repr_html_()

    def _shortest_path_by_metric(self, graph, start, end, idx):
        """
        Plain Dijkstra over `graph`, weighing each edge by tuple index `idx`
        (0=distance, 1=time, 2=fuel). Works on any graph dict shaped like
        self.mumbai_map, which lets k_shortest_paths() run it against
        temporarily-modified copies without touching the real graph.
        Returns (cost, path) or (inf, []) if no path exists.
        """
        if start not in graph or end not in graph:
            return float('infinity'), []

        distances = {node: float('infinity') for node in graph}
        distances[start] = 0
        previous = {node: None for node in graph}
        visited = set()
        pq = [(0, start)]

        while pq:
            current_cost, current_node = heapq.heappop(pq)
            if current_node in visited:
                continue
            visited.add(current_node)

            if current_node == end:
                break

            for neighbor, weights in graph.get(current_node, {}).items():
                new_cost = current_cost + weights[idx]
                if new_cost < distances.get(neighbor, float('infinity')):
                    distances[neighbor] = new_cost
                    previous[neighbor] = current_node
                    heapq.heappush(pq, (new_cost, neighbor))

        if distances.get(end, float('infinity')) == float('infinity'):
            return float('infinity'), []

        path = []
        node = end
        while node is not None:
            path.append(node)
            node = previous[node]
        path.reverse()

        return distances[end], path

    def dijkstra(self, start, end, metric='distance'):
        """
        Shortest path between start and end, optimizing for `metric`
        ('distance', 'time', or 'fuel'). Returns (cost, path, map_html);
        cost is only meaningful as an infinity check — use
        calculate_trip_details(path) for the real totals.
        """
        idx = METRIC_INDEX.get(metric, 0)
        cost, path = self._shortest_path_by_metric(self.mumbai_map, start,
                                                     end, idx)
        if not path:
            return float('infinity'), [], ""
        map_html = self.create_map_visualization(path)
        return cost, path, map_html

    def _path_cost(self, path, idx):
        cost = 0
        for i in range(len(path) - 1):
            cost += self.mumbai_map[path[i]][path[i + 1]][idx]
        return cost

    def k_shortest_paths(self, start, end, k=3, metric='distance'):
        """
        Up to k loopless alternate routes between start and end, ranked by
        `metric`, using Yen's algorithm on top of _shortest_path_by_metric.
        Returns a list of (cost, path) tuples, best first. The graph itself
        is never mutated — each candidate is explored on a deep copy.
        """
        idx = METRIC_INDEX.get(metric, 0)

        if start not in self.mumbai_map or end not in self.mumbai_map:
            return []

        first_cost, first_path = self._shortest_path_by_metric(
            self.mumbai_map, start, end, idx)
        if not first_path:
            return []

        A = [(first_cost, first_path)]
        B = []

        for _ in range(1, k):
            prev_path = A[-1][1]

            for i in range(len(prev_path) - 1):
                spur_node = prev_path[i]
                root_path = prev_path[:i + 1]

                working_graph = copy.deepcopy(self.mumbai_map)

                # Remove edges already used to reach this same root by any
                # path already accepted into A, so we don't just re-find it.
                for _, accepted_path in A:
                    if (len(accepted_path) > i
                            and accepted_path[:i + 1] == root_path):
                        u, v = accepted_path[i], accepted_path[i + 1]
                        working_graph.get(u, {}).pop(v, None)

                # Remove root-path nodes (other than the spur node) so the
                # spur search can't loop back through the root.
                for node in root_path[:-1]:
                    working_graph.pop(node, None)
                    for edges in working_graph.values():
                        edges.pop(node, None)

                spur_cost, spur_path = self._shortest_path_by_metric(
                    working_graph, spur_node, end, idx)

                if spur_path:
                    total_path = root_path[:-1] + spur_path
                    already_known = (total_path in [p for _, p in A]
                                      or total_path in [p for _, p in B])
                    if not already_known:
                        total_cost = self._path_cost(total_path, idx)
                        B.append((total_cost, total_path))

            if not B:
                break

            B.sort(key=lambda item: item[0])
            A.append(B.pop(0))

        return A

    def get_route_options(self, start, end, metric='distance', k=3):
        """
        Up to k ranked route options between start and end, each with its
        real distance/time/fuel totals (independent of which metric was
        used to rank it) and a rendered map. Empty list if no path exists.
        """
        candidates = self.k_shortest_paths(start, end, k=k, metric=metric)
        routes = []
        for _, path in candidates:
            distance, time, fuel = self.calculate_trip_details(path)
            routes.append({
                'path': path,
                'distance': distance,
                'time': time,
                'fuel': fuel,
                'map_html': self.create_map_visualization(path)
            })
        return routes

    def calculate_trip_details(self, path):
        total_distance = 0
        total_time = 0
        total_fuel = 0
        for i in range(len(path) - 1):
            distance, time, fuel = self.mumbai_map[path[i]][path[i + 1]]
            total_distance += distance
            total_time += time
            total_fuel += fuel
        return total_distance, total_time, total_fuel

    def get_location_info(self, name):
        location = self.locations[name]
        connections = self.mumbai_map[name]
        return {
            'name':
            location.name,
            'description':
            location.description,
            'connections': [{
                'name': neighbor,
                'distance': details[0],
                'time': details[1],
                'fuel': details[2]
            } for neighbor, details in connections.items()]
        }

    # ---------- MongoDB-only features ----------

    def log_search(self, start, end, distance, time, fuel):
        """Record a completed search. No-op if MongoDB isn't configured."""
        if not self.using_mongo:
            return
        self.db.searches.insert_one({
            'start': start,
            'end': end,
            'distance': distance,
            'time': time,
            'fuel': fuel,
            'timestamp': datetime.now(timezone.utc)
        })

    def get_popular_routes(self, limit=5):
        """Most-searched start/end pairs. Returns [] if MongoDB isn't configured."""
        if not self.using_mongo:
            return []
        pipeline = [
            {'$group': {
                '_id': {'start': '$start', 'end': '$end'},
                'count': {'$sum': 1}
            }},
            {'$sort': {'count': -1}},
            {'$limit': limit}
        ]
        return [{
            'start': doc['_id']['start'],
            'end': doc['_id']['end'],
            'count': doc['count']
        } for doc in self.db.searches.aggregate(pipeline)]

    def add_location(self, name, description, lat, lon, connections=None):
        """
        Add a new location (and optional road connections) without editing code.
        connections: list of {'to': name, 'distance': km, 'time': min, 'fuel': L}
        Requires MongoDB; raises RuntimeError otherwise.
        """
        if not self.using_mongo:
            raise RuntimeError(
                'Adding locations requires MongoDB. Set MONGO_URI.')

        self.db.locations.update_one(
            {'name': name},
            {'$set': {
                'name': name,
                'description': description,
                'lat': lat,
                'lon': lon
            }},
            upsert=True)

        for conn in (connections or []):
            self.db.edges.insert_one({
                'from': name,
                'to': conn['to'],
                'distance': conn['distance'],
                'time': conn['time'],
                'fuel': conn['fuel']
            })

        # Reload in-memory graph so the change is live immediately.
        self.locations, self.mumbai_map = self._load_from_mongo()
        self.sorted_locations = sorted(self.locations.keys())
