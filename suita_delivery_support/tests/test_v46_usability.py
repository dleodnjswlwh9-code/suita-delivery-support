"""Guard readability and route-review interactions against accidental regression."""
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
        # Long visits list must not push the route map below the fold.
        self.assertLess(self.routes.index('<div class="p2-mapbox"'),self.routes.index('<div id="p2-route-detail"'))
    def test_visit_leg_navigation_and_vehicle_search(self):
        for token in ('p2-step-prev','p2-step-next','p2-step-all','p2-search-vehicle','p2-view-all','data-leg-index'):
            self.assertIn(token,self.routes)
    def test_colored_repeated_direction_arrows(self):
        self.assertIn('FORWARD_CLOSED_ARROW',self.routes)
        self.assertIn("fillColor:color,fillOpacity:1",self.routes)
        self.assertIn("repeat:single?'135px':'200px'",self.routes)
        self.assertIn('p2-seq-current',self.routes)
    def test_global_navigation_accessibility(self):
        self.assertIn('v46-workflow',self.base)
        self.assertIn('v46-skip-link',self.base)
        self.assertIn('aria-current="step"',self.base)
        self.assertIn('focus-visible',self.css)
    def test_small_screen_css(self):
        self.assertIn('@media(max-width:600px)',self.css)
        self.assertIn('.v46-vehicle-search',self.css)
