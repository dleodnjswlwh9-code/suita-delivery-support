"""Integration constraints for the selectable-aspiration, one-budget P1."""
import unittest
from p1_full_constraints import optimize_joint_p1
from p1_optimizer import P1InputError

def row(d=100,b=0,visited=True,target=.8):
    return dict(demandKg=d,securedKg=b,targetRate=target,visited=visited)

class UnifiedP1Tests(unittest.TestCase):
    def solve(self, f, w, total, **kw):
        target=kw.get('target',.8)
        return optimize_joint_p1(f,w,total,kw.get('rho',.001),kw.get('delta',.5),
                                 kw.get('rounds',1),[{'capacityKg':2000,'count':kw.get('count',1)}],target)

    def test_target_weights(self):
        for target,weight in [(.7,10/3),(.8,5),(.9,10)]:
            with self.subTest(target=target):
                r=self.solve([row(target=target)],[row(target=target)],50,target=target)
                self.assertAlmostEqual(r['weight'],weight)
                self.assertAlmostEqual(r['targetRate'],target)
                self.assertAlmostEqual(r['usedFoodKg']+r['usedWaterKg'],50)
                self.assertAlmostEqual(r['combinedRates'][0],.25)

    def test_budget_not_split_as_input(self):
        r=self.solve([row()],[row()],60)
        self.assertAlmostEqual(r['usedFoodKg'],30)
        self.assertAlmostEqual(r['usedWaterKg'],30)
        self.assertAlmostEqual(r['unusedTotalKg'],0)

    def test_balanced_shelters(self):
        r=self.solve([row(),row()],[row(),row()],100)
        self.assertAlmostEqual(r['combinedRates'][0],r['combinedRates'][1])

    def test_not_ship_excess_when_one_good_complete(self):
        r=self.solve([row(100,100)],[row(100,0)],50)
        self.assertAlmostEqual(r['usedFoodKg'],0)
        self.assertAlmostEqual(r['usedWaterKg'],50)

    def test_mandatory_lower_bound(self):
        r=self.solve([row(visited=False),row(visited=False)],
                     [row(visited=False),row(visited=False)],2,delta=.5)
        self.assertEqual(r['mandatoryCount'],2)
        for f,w in zip(r['allocationsFoodKg'],r['allocationsWaterKg']):
            self.assertGreaterEqual(f+w,.5-1e-5)

    def test_insufficient_budget_rejected(self):
        with self.assertRaisesRegex(P1InputError,'最低配送量'):
            self.solve([row(visited=False),row(visited=False)],
                       [row(visited=False),row(visited=False)],1,delta=1)

    def test_two_tons_capacity(self):
        r=self.solve([row(10000)],[row(10000)],10000)
        self.assertLessEqual(r['usedFoodKg']+r['usedWaterKg'],2000+1e-5)

    def test_target_is_not_cap(self):
        r=self.solve([row(100,50)],[row(100,50)],100)
        self.assertAlmostEqual(r['combinedRates'][0],1)

    def test_only_2ton_truck(self):
        with self.assertRaisesRegex(P1InputError,'2t'):
            optimize_joint_p1([row()],[row()],50,.001,.5,1,
                              [{'capacityKg':4000,'count':1}],.8)

    def test_invalid_target(self):
        with self.assertRaisesRegex(P1InputError,'希求水準'):
            self.solve([row(target=.75)],[row(target=.75)],50,target=.75)

    def test_rows_target_mismatch(self):
        with self.assertRaisesRegex(P1InputError,'希求水準'):
            self.solve([row(target=.9)],[row(target=.9)],50,target=.8)

    def test_micro_remaining(self):
        r=self.solve([row(10,9.8)],[row(10,9.9)],5,delta=.5)
        self.assertIsNone(r['objectiveF1'])
        self.assertEqual(r['microCount'],1)

    def test_more_vehicles(self):
        f=[row(10000),row(10000)];w=[row(10000),row(10000)]
        a=self.solve(f,w,10000,count=1);b=self.solve(f,w,10000,count=2)
        self.assertGreater(b['usedFoodKg']+b['usedWaterKg'],a['usedFoodKg']+a['usedWaterKg'])

    def test_invalid_truck_count(self):
        with self.assertRaises(P1InputError):
            self.solve([row()],[row()],10,count=0)

if __name__=='__main__':unittest.main()
