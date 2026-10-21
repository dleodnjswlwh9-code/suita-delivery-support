import unittest
from kit_planning import clean_input,solve_p1,stock_to_kits,KitInputError,TRUCK_CAP_KITS
from p2_kit_optimizer import optimize_p2_kit


def rows(n=8):
    return [dict(name=f'避難所{i+1}',lat=34.75+i*.004,lng=135.52+i*.003,demandKits=100,stockKits=10)
            for i in range(n)]

def payload(n=8,supply=380,trucks=2,rounds=3):
    return dict(shelters=rows(n),totalKits=supply,targetRate=.8,rho=.001,
                minKits=1,maxRounds=rounds,truckCount=trucks)


class CompleteKitTests(unittest.TestCase):
    def test_complete_kit_with_unmatched_stock(self):
        self.assertEqual(stock_to_kits({'retortRice':300,'water500ml':300}),(50,150,0))
        self.assertEqual(stock_to_kits({'retortRice':99,'water500ml':119}),(19,42,5))
    def test_truck_capacity_kits(self):
        self.assertEqual(TRUCK_CAP_KITS,444)
    def test_p1_single_kit_balance(self):
        x=solve_p1(clean_input(payload()))
        self.assertEqual(len(x['allocations']),8)
        self.assertAlmostEqual(sum(x['allocations']),380)
        self.assertTrue(all(v>=1 for v in x['allocations']))
    def test_p2_physical_constraints(self):
        o=optimize_p2_kit(payload())
        self.assertEqual(o['shelterCount'],8)
        self.assertEqual(o['visitedShelters'],8)
        self.assertEqual(o['deliveredKits'],380)
        self.assertEqual(sum(x['kits'] for x in o['routes']),380)
        self.assertTrue(all(x['kits']<=TRUCK_CAP_KITS for x in o['routes']))
        self.assertTrue(all(isinstance(x['kits'],int) for x in o['routes']))
        self.assertAlmostEqual(o['f2Minutes'],sum(o['roundTimesMinutes']),places=1)
        for r in range(1,4):
            stops=[s['index'] for route in o['routes'] if route['round']==r for s in route['stops']]
            self.assertEqual(len(stops),len(set(stops)))
    def test_fixed_f3_horizon(self):
        o=optimize_p2_kit(payload(n=5,supply=30,rounds=4,trucks=2))
        self.assertEqual(len(o['f3ByRound']),3)
        self.assertAlmostEqual(o['f3'],sum(o['f3ByRound']),places=5)
    def test_small_inventory_fails_mandatory_visits(self):
        with self.assertRaises(KitInputError):optimize_p2_kit(payload(n=8,supply=7))
    def test_excess_p1_score_not_mislabeled_p0_eta(self):
        o=optimize_p2_kit(payload(n=8,supply=383))
        self.assertEqual(o['etaAssumed'],0)
        self.assertAlmostEqual(o['f1Excess'],max(0,o['f1Route']-o['f1Star']))
        self.assertEqual(o['isValidatedP2'],o['f1Excess']<=max(1e-7,1e-8*abs(o['f1Star'])))

if __name__=='__main__':unittest.main()
