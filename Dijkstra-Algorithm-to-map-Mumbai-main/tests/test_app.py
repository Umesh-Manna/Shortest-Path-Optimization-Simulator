"""
Integration tests for the Flask app's HTTP endpoints, using Flask's
built-in test client (no real server or network needed). Run with:

    python -m unittest discover -s tests
"""

import unittest

from main import app


class TestFlaskEndpoints(unittest.TestCase):

    def setUp(self):
        app.testing = True
        self.client = app.test_client()

    def test_index_loads(self):
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Mumbai Map Navigator', resp.data)

    def test_find_path_success(self):
        resp = self.client.post('/find_path', data={
            'start': 'Bandra', 'end': 'Dadar'
        })
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data['path'], 'Bandra -> Dadar')
        self.assertIn('routes', data)

    def test_find_path_with_metric(self):
        resp = self.client.post('/find_path', data={
            'start': 'Chhatrapati Shivaji Terminus', 'end': 'Andheri',
            'metric': 'time'
        })
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data['metric'], 'time')

    def test_find_path_invalid_metric_falls_back(self):
        resp = self.client.post('/find_path', data={
            'start': 'Bandra', 'end': 'Dadar', 'metric': 'nonsense'
        })
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data['metric'], 'distance')

    def test_find_path_unknown_location_suggests_alternatives(self):
        resp = self.client.post('/find_path', data={
            'start': 'Bandraa', 'end': 'Dadar'
        })
        data = resp.get_json()
        self.assertIn('error', data)
        self.assertIn('Bandra', data['start_suggestions'])

    def test_location_info_known_location(self):
        resp = self.client.post('/location_info', data={'name': 'Bandra'})
        data = resp.get_json()
        self.assertEqual(data['name'], 'Bandra')

    def test_location_info_unknown_location(self):
        resp = self.client.post('/location_info', data={'name': 'Atlantis'})
        data = resp.get_json()
        self.assertIn('error', data)

    def test_popular_routes_returns_list(self):
        resp = self.client.get('/popular_routes')
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.get_json(), list)


class TestAddLocationValidation(unittest.TestCase):
    """
    These test input validation, which runs before the MongoDB check —
    so they pass whether or not MongoDB is configured.
    """

    def setUp(self):
        app.testing = True
        self.client = app.test_client()

    def test_missing_name_rejected(self):
        resp = self.client.post('/add_location', json={
            'lat': 19.0, 'lon': 72.8
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn('name', resp.get_json()['error'])

    def test_missing_coordinates_rejected(self):
        resp = self.client.post('/add_location', json={'name': 'Worli'})
        self.assertEqual(resp.status_code, 400)

    def test_out_of_region_latitude_rejected(self):
        resp = self.client.post('/add_location', json={
            'name': 'Worli', 'lat': 40.7128, 'lon': -74.0060  # New York
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn('lat', resp.get_json()['error'])

    def test_connection_to_unknown_location_rejected(self):
        resp = self.client.post('/add_location', json={
            'name': 'Worli', 'lat': 19.0176, 'lon': 72.8161,
            'connections': [
                {'to': 'Atlantis', 'distance': 3, 'time': 10, 'fuel': 0.5}
            ]
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Atlantis', resp.get_json()['error'])

    def test_negative_connection_distance_rejected(self):
        resp = self.client.post('/add_location', json={
            'name': 'Worli', 'lat': 19.0176, 'lon': 72.8161,
            'connections': [
                {'to': 'Bandra', 'distance': -3, 'time': 10, 'fuel': 0.5}
            ]
        })
        self.assertEqual(resp.status_code, 400)

    def test_valid_payload_either_succeeds_or_needs_mongo(self):
        resp = self.client.post('/add_location', json={
            'name': 'Worli', 'description': 'Coastal suburb',
            'lat': 19.0176, 'lon': 72.8161,
            'connections': [
                {'to': 'Mahalaxmi', 'distance': 4, 'time': 15, 'fuel': 1.0}
            ]
        })
        # 200 if MongoDB is configured, 400 with a MongoDB-specific
        # message if it isn't — either way, it must have passed
        # validation to get this far (not a generic 400).
        if resp.status_code == 400:
            self.assertIn('MongoDB', resp.get_json()['error'])
        else:
            self.assertTrue(resp.get_json()['success'])


if __name__ == '__main__':
    unittest.main()
