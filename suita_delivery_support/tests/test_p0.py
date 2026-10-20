"""P0 basic model regression: one pooled hub and joint two-good aspiration."""
import unittest
from p0_optimizer import optimize_p0
from p1_optimizer import P1InputError


def commodity(d,b,visited=False):
    return dict(demandKg=d, securedKg=b, targetRate=.8, visited=visited)


class P0Tests(unittest.TestCase):
    def test_gap_for_minimum_visit_unit(self):
        # Food short at two already-visited shelters. P1 may split 5+5,
        # but P0 can only deliver 10 to one shelter in the sole visit round.
        f=[commodity(100,10,True),commodity(100,10,True)]
        w=[commodity(100,100,True),commodity(100,100,True)]
        r=optimize_p0(f,w,10,.1,10,1,1,.8)
        self.assertTrue(r['optimal'])
        self.assertAlmostEqual(r['gapEta'],.25,places=5)
        self.assertAlmostEqual(r['totalFoodKg'],10)
        self.assertEqual(r['visitedShelters'],1)

    def test_mandatory_visits_do_not_infer_visit_from_stock(self):
        f=[commodity(100,10),commodity(100,10)]
        w=[commodity(100,20),commodity(100,20)]
        r=optimize_p0(f,w,10,.001,2,1,1,.8)
        self.assertEqual(r['mandatoryCount'],2)
        self.assertEqual(r['visitedShelters'],2)
        self.assertEqual(len(r['roundAssignments']),1)
        self.assertLessEqual(r['roundAssignments'][0]['loadKg'],2000+1e-6)
        for visit in r['roundAssignments'][0]['visits']:
            self.assertGreaterEqual(visit['totalKg'],2-1e-6)

    def test_vehicle_capacity_and_shared_stock(self):
        f=[commodity(5000,0),commodity(5000,0)]
        w=[commodity(5000,0),commodity(5000,0)]
        r=optimize_p0(f,w,8000,.001,.5,1,1,.8)
        self.assertLessEqual(r['totalFoodKg']+r['totalWaterKg'],2000+1e-5)
        self.assertTrue(r['optimal'])

    def test_visits_precondition_caught(self):
        f=[commodity(5000,0),commodity(5000,0)]
        w=[commodity(5000,0),commodity(5000,0)]
        with self.assertRaises(P1InputError):
            optimize_p0(f,w,3000,.001,1500,1,1,.8)

    def test_two_rounds(self):
        f=[commodity(1500,0),commodity(1500,0)]
        w=[commodity(1500,0),commodity(1500,0)]
        r=optimize_p0(f,w,4000,.001,1500,2,1,.8)
        self.assertEqual(r['visitedShelters'],2)
        self.assertEqual(r['usedRounds'],2)
        self.assertTrue(all(a['loadKg']<=2000+1e-5 for a in r['roundAssignments']))

    def test_rejects_unbounded_instance(self):
        with self.assertRaisesRegex(P1InputError,'計算上限'):
            optimize_p0([commodity(100,0)],[commodity(100,0)],100,.001,.5,1,21,.8)


if __name__=='__main__':unittest.main()
