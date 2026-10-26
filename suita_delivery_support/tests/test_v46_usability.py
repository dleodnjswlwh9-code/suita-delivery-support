"""Updated visible-controls requirements for the deliberately simplified v48 UI."""
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class UsabilityRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.routes=(ROOT/'templates/routes.html').read_text()
        cls.base=(ROOT/'templates/base.html').read_text()
        cls.css=(ROOT/'static/style.css').read_text()
    def test_route_detail_after_map(self):
        self.assertLess(self.routes.index('<div class="p2-mapbox"'),self.routes.index('<div id="p2-route-detail"'))
    def test_automatic_overview_and_card_drill_down(self):
        self.assertNotIn('<div class="p2-journey-toolbar"',self.routes)
        self.assertNotIn('<div id="p2-leg-navigator"',self.routes)
        self.assertNotIn('<div class="v46-vehicle-search"',self.routes)
        self.assertIn("round.value='all';truck.value='all'",self.routes)
        self.assertIn("$('p2-vehicle-list').addEventListener('click'",self.routes)
        self.assertIn('truckColor(rt.truck)',self.routes)
    def test_clean_sparse_direction_arrows(self):
        self.assertIn('FORWARD_CLOSED_ARROW',self.routes)
        self.assertIn('legIndex%3===0',self.routes)
        self.assertIn('function drivingLane(path,single)',self.routes)
    def test_global_navigation_accessibility(self):
        self.assertIn('v46-workflow',self.base)
        self.assertIn('v46-skip-link',self.base)
        self.assertIn('aria-current="step"',self.base)
        self.assertIn('focus-visible',self.css)
    def test_small_screen_css(self):
        self.assertIn('@media(max-width:600px)',self.css)
        self.assertIn('.p2-ui .p2-map-layout .p2-mapbox',self.css)
