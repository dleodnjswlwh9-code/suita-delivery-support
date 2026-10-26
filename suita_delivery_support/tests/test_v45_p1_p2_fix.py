"""Regression tests for v45 feasibility and directions work; P0 intentionally untouched."""
import unittest
from kit_planning import clean_input,solve_p1,round_integer_p1,KitInputError,TRUCK_CAP_KITS
from p2_kit_optimizer import optimize_p2_kit


def item(name,lat,lng,demand,stock=0):
    return dict(name=name,lat=lat,lng=lng,demandKits=demand,stockKits=stock)

def case(rows,budget,delta=10,trucks=3,rounds=1):
    return dict(shelters=rows,totalKits=budget,targetRate=.8,rho=.001,
                minKits=delta,maxRounds=rounds,truckCount=trucks)

class V45Corrections(unittest.TestCase):
    def test_single_visit_upper_bound_paper_26(self):
        p=case([item('A',34.78,135.53,1000)],1000)
        c=clean_input(p);a=solve_p1(c)
        self.assertAlmostEqual(a['allocations'][0],TRUCK_CAP_KITS)
        self.assertEqual(round_integer_p1(c,a),[TRUCK_CAP_KITS])
        delivered=optimize_p2_kit(p)
        self.assertEqual(delivered['deliveredKits'],TRUCK_CAP_KITS)
        self.assertTrue(all(route['kits']<=TRUCK_CAP_KITS for route in delivered['routes']))

    def test_10_kit_reassignment_between_hubs(self):
        rows=[item('N1',34.80,135.532,260),item('N2',34.803,135.53,260),
              item('N3',34.802,135.52,220),item('S1',34.771,135.535,160)]
        result=optimize_p2_kit(case(rows,900,10,3,1))
        self.assertEqual(result['assignmentMethod'],'MILP-capacity-repair')
        self.assertEqual(result['deliveredKits'],900)
        self.assertEqual(result['visitedShelters'],4)
        self.assertEqual(len([r for r in result['routes'] if r['kits']>0]),3)
        self.assertTrue(all(stop['kits']>=10 for route in result['routes'] for stop in route['stops']))

    def test_zero_demand_is_not_fabricated(self):
        rows=[item('Empty',34.78,135.52,0),item('Needs',34.79,135.53,100)]
        p=case(rows,30)
        c=clean_input(p)
        self.assertEqual(c['rows'][0]['demand'],0)
        result=optimize_p2_kit(p)
        self.assertEqual(result['zeroDemandShelters'],1)
        self.assertEqual(result['visitedShelters'],1)
        self.assertEqual(result['deliveredKits'],30)

    def test_precise_shortage_message(self):
        rows=[item('A',34.76,135.52,100),item('B',34.77,135.53,100)]
        with self.assertRaisesRegex(KitInputError,'不足1人日分'):
            solve_p1(clean_input(case(rows,19,10)))

    def test_p1_reference_mismatch_is_not_silent(self):
        rows=[item('A',34.76,135.52,100)]
        p=case(rows,30);p['p1ReferenceF1']=123.456
        with self.assertRaisesRegex(KitInputError,'P1とP2の入力条件が一致しません'):
            optimize_p2_kit(p)
        p['p1ReferenceF1']=solve_p1(clean_input(p))['f1']
        self.assertEqual(optimize_p2_kit(p)['deliveredKits'],30)

if __name__=='__main__':unittest.main()
