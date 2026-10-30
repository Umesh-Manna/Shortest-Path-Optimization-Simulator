"""
Unit tests for MumbaiMapNavigator's routing logic.

These run against the built-in fallback data (no MONGO_URI needed), so
they work the same in CI as they do locally. Run with:

    python -m unittest discover -s tests
"""

import unittest

from mumbai_map_navigator import MumbaiMapNavigator


class TestDijkstra(unittest.TestCase):

    def setUp(self):
        self.nav = MumbaiMapNavigator()

    def test_direct_neighbor_path(self):
        distance, path, map_html = self.nav.dijkstra('Bandra', 'Dadar')
        self.assertEqual(path, ['Bandra', 'Dadar'])
        self.assertEqual(distance, 7)
        self.assertTrue(map_html)  # non-empty rendered map

    def test_multi_hop_path(self):
        distance, path, _ = self.nav.dijkstra(
            'Chhatrapati Shivaji Terminus', 'Andheri')
        self.assertEqual(path[0], 'Chhatrapati Shivaji Terminus')
        self.assertEqual(path[-1], 'Andheri')
        self.assertGreater(len(path), 2)

    def test_same_start_and_end(self):
        distance, path, _ = self.nav.dijkstra('Bandra', 'Bandra')
        self.assertEqual(path, ['Bandra'])
        self.assertEqual(distance, 0)

    def test_unknown_node_returns_no_path(self):
        distance, path, map_html = self.nav.dijkstra('Nowhere', 'Bandra')
        self.assertEqual(path, [])
        self.assertEqual(distance, float('infinity'))
        self.assertEqual(map_html, '')

    def test_calculate_trip_details_matches_edges(self):
        _, path, _ = self.nav.dijkstra('Bandra', 'Dadar')
        distance, time, fuel = self.nav.calculate_trip_details(path)
        self.assertEqual((distance, time, fuel), (7, 30, 1.7))


class TestMultiCriteriaRouting(unittest.TestCase):

    def setUp(self):
        self.nav = MumbaiMapNavigator()

    def test_all_metrics_find_a_path(self):
        for metric in ('distance', 'time', 'fuel'):
            _, path, _ = self.nav.dijkstra(
                'Chhatrapati Shivaji Terminus', 'Dadar', metric=metric)
            self.assertEqual(path[0], 'Chhatrapati Shivaji Terminus')
            self.assertEqual(path[-1], 'Dadar')

    def test_unknown_metric_falls_back_to_distance(self):
        cost_a, path_a, _ = self.nav.dijkstra('Bandra', 'Dadar',
                                               metric='distance')
        cost_b, path_b, _ = self.nav.dijkstra('Bandra', 'Dadar',
                                               metric='not-a-real-metric')
        self.assertEqual(path_a, path_b)
        self.assertEqual(cost_a, cost_b)


class TestKShortestPaths(unittest.TestCase):

    def setUp(self):
        self.nav = MumbaiMapNavigator()

    def test_returns_at_least_one_route(self):
        results = self.nav.k_shortest_paths(
            'Chhatrapati Shivaji Terminus', 'Bandra', k=3)
        self.assertGreaterEqual(len(results), 1)

    def test_routes_are_unique(self):
        results = self.nav.k_shortest_paths(
            'Chhatrapati Shivaji Terminus', 'Bandra', k=3)
        paths = [tuple(path) for _, path in results]
        self.assertEqual(len(paths), len(set(paths)))

    def test_routes_are_ranked_ascending_by_cost(self):
        results = self.nav.k_shortest_paths(
            'Chhatrapati Shivaji Terminus', 'Bandra', k=3)
        costs = [cost for cost, _ in results]
        self.assertEqual(costs, sorted(costs))

    def test_best_route_matches_plain_dijkstra(self):
        _, dijkstra_path, _ = self.nav.dijkstra(
            'Chhatrapati Shivaji Terminus', 'Bandra')
        k_results = self.nav.k_shortest_paths(
            'Chhatrapati Shivaji Terminus', 'Bandra', k=3)
        self.assertEqual(k_results[0][1], dijkstra_path)

    def test_no_path_returns_empty_list(self):
        results = self.nav.k_shortest_paths('Nowhere', 'Bandra', k=3)
        self.assertEqual(results, [])

    def test_original_graph_is_not_mutated(self):
        before = len(self.nav.mumbai_map['Bandra'])
        self.nav.k_shortest_paths(
            'Chhatrapati Shivaji Terminus', 'Andheri', k=3)
        after = len(self.nav.mumbai_map['Bandra'])
        self.assertEqual(before, after)


class TestGetRouteOptions(unittest.TestCase):

    def setUp(self):
        self.nav = MumbaiMapNavigator()

    def test_each_route_has_real_totals_and_map(self):
        routes = self.nav.get_route_options(
            'Chhatrapati Shivaji Terminus', 'Bandra', metric='time', k=3)
        self.assertGreaterEqual(len(routes), 1)
        for route in routes:
            self.assertIn('path', route)
            self.assertIn('distance', route)
            self.assertIn('time', route)
            self.assertIn('fuel', route)
            self.assertTrue(route['map_html'])

    def test_no_path_returns_empty_list(self):
        routes = self.nav.get_route_options('Nowhere', 'Bandra')
        self.assertEqual(routes, [])


class TestLookupHelpers(unittest.TestCase):

    def setUp(self):
        self.nav = MumbaiMapNavigator()

    def test_find_location_exact_match(self):
        self.assertEqual(self.nav.find_location('Bandra'), 'Bandra')

    def test_find_location_unknown_returns_none(self):
        self.assertIsNone(self.nav.find_location('Atlantis'))

    def test_fuzzy_search_suggests_close_match(self):
        matches = self.nav.fuzzy_search('Bandraa')
        self.assertIn('Bandra', matches)

    def test_get_location_info_includes_connections(self):
        info = self.nav.get_location_info('Bandra')
        self.assertEqual(info['name'], 'Bandra')
        names = [c['name'] for c in info['connections']]
        self.assertIn('Dadar', names)
        self.assertIn('Juhu', names)


class TestMongoFallbackBehavior(unittest.TestCase):
    """
    These only assert behavior that holds true when MongoDB isn't
    configured (the default in CI/local dev without MONGO_URI set).
    """

    def setUp(self):
        self.nav = MumbaiMapNavigator()

    def test_log_search_is_a_safe_no_op(self):
        if not self.nav.using_mongo:
            # Should not raise even though there's nowhere to write to.
            self.nav.log_search('Bandra', 'Dadar', 7, 30, 1.7)

    def test_popular_routes_empty_without_mongo(self):
        if not self.nav.using_mongo:
            self.assertEqual(self.nav.get_popular_routes(), [])

    def test_add_location_raises_without_mongo(self):
        if not self.nav.using_mongo:
            with self.assertRaises(RuntimeError):
                self.nav.add_location('Worli', 'test', 19.0176, 72.8161)


if __name__ == '__main__':
    unittest.main()
