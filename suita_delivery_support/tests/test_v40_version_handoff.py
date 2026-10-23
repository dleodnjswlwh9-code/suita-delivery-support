"""Regression checks for the P1-to-P2 version/setting handoff."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class P1P2VersionHandoff(unittest.TestCase):
    def test_shared_schema_identifier(self):
        app=(ROOT/'app.py').read_text(encoding='utf-8')
        self.assertIn('ALLOCATION_SCHEMA_VERSION = "v39-complete-kit-p1"', app)
        self.assertIn('"allocation_schema_version": ALLOCATION_SCHEMA_VERSION', app)
        for filename in ('allocation.html','routes.html','plan.html'):
            text=(ROOT/'templates'/filename).read_text(encoding='utf-8')
            self.assertIn('allocation_schema_version | tojson', text)
            self.assertNotIn('v34-complete-kit-p1', text)

    def test_effective_p1_settings_persisted_for_p2(self):
        alloc=(ROOT/'templates'/'allocation.html').read_text(encoding='utf-8')
        self.assertIn('effectiveDeliverySettings',alloc)
        self.assertIn("sessionStorage.setItem('p1DeliverySettings', JSON.stringify(effectiveDeliverySettings))",alloc)
        route=(ROOT/'templates'/'routes.html').read_text(encoding='utf-8')
        self.assertIn('const good=schemaReady&&settingsMatch;',route)
        self.assertIn('if(!settingsMatch)',route)

if __name__=='__main__':
    unittest.main()
