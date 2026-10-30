from flask import Flask, render_template, request, jsonify
from mumbai_map_navigator import MumbaiMapNavigator, METRIC_INDEX

app = Flask(__name__)
navigator = MumbaiMapNavigator()

# Roughly Mumbai + its immediate suburbs — used to sanity-check new
# locations submitted via /add_location so bad coordinates don't
# silently produce a map centered on the wrong city.
MUMBAI_LAT_RANGE = (18.80, 19.35)
MUMBAI_LON_RANGE = (72.70, 73.05)

MAX_NAME_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 500


def validate_add_location_payload(data):
    """
    Validates a POST /add_location payload. Returns (cleaned_dict, None)
    on success, or (None, error_message) on the first problem found.
    """
    name = str(data.get('name', '')).strip()
    if not name:
        return None, 'name is required'
    if len(name) > MAX_NAME_LENGTH:
        return None, f'name must be {MAX_NAME_LENGTH} characters or fewer'

    description = str(data.get('description', '')).strip()
    if len(description) > MAX_DESCRIPTION_LENGTH:
        return None, f'description must be {MAX_DESCRIPTION_LENGTH} characters or fewer'

    try:
        lat = float(data['lat'])
        lon = float(data['lon'])
    except (KeyError, TypeError, ValueError):
        return None, 'lat and lon are required and must be numbers'

    if not (MUMBAI_LAT_RANGE[0] <= lat <= MUMBAI_LAT_RANGE[1]):
        return None, (f'lat must be between {MUMBAI_LAT_RANGE[0]} and '
                       f'{MUMBAI_LAT_RANGE[1]} (Mumbai region)')
    if not (MUMBAI_LON_RANGE[0] <= lon <= MUMBAI_LON_RANGE[1]):
        return None, (f'lon must be between {MUMBAI_LON_RANGE[0]} and '
                       f'{MUMBAI_LON_RANGE[1]} (Mumbai region)')

    raw_connections = data.get('connections', [])
    if not isinstance(raw_connections, list):
        return None, 'connections must be a list'

    connections = []
    for i, conn in enumerate(raw_connections):
        if not isinstance(conn, dict) or 'to' not in conn:
            return None, f'connections[{i}] must include a "to" location'

        target = str(conn['to']).strip()
        if target == name:
            return None, f'connections[{i}] cannot connect a location to itself'
        if target not in navigator.locations:
            return None, f'connections[{i}]: unknown location "{target}"'

        try:
            distance = float(conn['distance'])
            time = float(conn['time'])
            fuel = float(conn['fuel'])
        except (KeyError, TypeError, ValueError):
            return None, f'connections[{i}] needs numeric distance, time and fuel'

        if distance <= 0 or time <= 0 or fuel <= 0:
            return None, f'connections[{i}]: distance, time and fuel must be positive'

        connections.append({
            'to': target,
            'distance': distance,
            'time': time,
            'fuel': fuel
        })

    return {
        'name': name,
        'description': description,
        'lat': lat,
        'lon': lon,
        'connections': connections
    }, None


@app.route('/')
def index():
    return render_template('index.html', locations=navigator.sorted_locations)


@app.route('/find_path', methods=['POST'])
def find_path():
    start = request.form['start']
    end = request.form['end']
    metric = request.form.get('metric', 'distance')
    if metric not in METRIC_INDEX:
        metric = 'distance'

    start_match = navigator.find_location(start)
    end_match = navigator.find_location(end)

    if not start_match or not end_match:
        return jsonify({
            'error': 'Invalid locations',
            'start_suggestions': navigator.fuzzy_search(start),
            'end_suggestions': navigator.fuzzy_search(end)
        })

    routes = navigator.get_route_options(start_match, end_match, metric=metric, k=3)

    if not routes:
        return jsonify(
            {'error': f"No path found between {start_match} and {end_match}"})

    best = routes[0]
    navigator.log_search(start_match, end_match, best['distance'],
                          best['time'], best['fuel'])

    return jsonify({
        'success': True,
        'start': start_match,
        'end': end_match,
        'metric': metric,
        'path': ' -> '.join(best['path']),
        'distance': best['distance'],
        'time': best['time'],
        'fuel': best['fuel'],
        'map_html': best['map_html'],
        'routes': [{
            'path': ' -> '.join(r['path']),
            'distance': r['distance'],
            'time': r['time'],
            'fuel': r['fuel'],
            'map_html': r['map_html']
        } for r in routes]
    })


@app.route('/location_info', methods=['POST'])
def location_info():
    name = request.form['name']
    location = navigator.find_location(name)

    if location:
        info = navigator.get_location_info(location)
        return jsonify(info)
    else:
        return jsonify({
            'error': f"Location '{name}' not found",
            'suggestions': navigator.fuzzy_search(name)
        })


@app.route('/popular_routes')
def popular_routes():
    # Empty list if MongoDB isn't configured — front end just hides the section.
    return jsonify(navigator.get_popular_routes(limit=5))


@app.route('/add_location', methods=['POST'])
def add_location():
    """
    Add a new location (and optional connections) without touching code.
    Requires MongoDB (MONGO_URI set). Body (form or JSON):
      name, description, lat, lon,
      connections: JSON list of {to, distance, time, fuel}  (optional)
    """
    data = request.get_json(silent=True) or request.form

    cleaned, error = validate_add_location_payload(data)
    if error:
        return jsonify({'error': error}), 400

    try:
        navigator.add_location(cleaned['name'], cleaned['description'],
                                cleaned['lat'], cleaned['lon'],
                                cleaned['connections'])
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 400

    return jsonify({
        'success': True,
        'locations': navigator.sorted_locations
    })


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
