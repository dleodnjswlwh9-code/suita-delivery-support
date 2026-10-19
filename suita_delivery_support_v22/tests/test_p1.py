"""Check unified two-commodity P1 against its LP specification."""
import unittest
from p1_full_constraints import optimize_joint_p1
from p1_optimizer import P1InputError

def row(d=100,b=0,visited=True):
    return dict(demandKg=d,securedKg=b,targetRate=.8,visited=visited)

class UnifiedP1Tests(unittest.TestCase):
    def solve(self,f,w,fs,ws,**kw):
        return optimize_joint_p1(f,w,fs,ws,kw.get('rho',.001),kw.get('delta',.5),
                                 kw.get('rounds',1),[{'capacityKg':2000,'count':kw.get('count',1)}])

    def test_single_weight_and_target(self):
        r=self.solve([row()],[row()],25,25)
        self.assertAlmostEqual(r['weight'],5)
        self.assertEqual(r['targetRate'],.8)
        self.assertAlmostEqual(r['allocationsFoodKg'][0],25)
        self.assertAlmostEqual(r['allocationsWaterKg'][0],25)
        self.assertAlmostEqual(r['combinedRates'][0],.25)

    def test_balanced_two_shelters(self):
        r=self.solve([row(),row()],[row(),row()],50,50)
        self.assertAlmostEqual(r['combinedRates'][0],r['combinedRates'][1],places=7)
        self.assertAlmostEqual(r['theta'],5*(.8-.25))

    def test_both_goods_required_for_rate(self):
        r=self.solve([row()],[row()],100,0)
        self.assertAlmostEqual(r['combinedRates'][0],0)
        self.assertAlmostEqual(r['usedFoodKg'],0,places=6)

    def test_mandatory_lower_bound(self):
        r=self.solve([row(visited=False),row(visited=False)],
                     [row(visited=False),row(visited=False)],1,1,delta=.5)
        self.assertEqual(r['mandatoryCount'],2)
        for f,w in zip(r['allocationsFoodKg'],r['allocationsWaterKg']):self.assertGreaterEqual(f+w,.5-1e-6)

    def test_inventory_shortage_detected(self):
        with self.assertRaisesRegex(P1InputError,'最低配送量'):
            self.solve([row(visited=False),row(visited=False)],
                       [row(visited=False),row(visited=False)],.1,.1,delta=1)

    def test_vehicle_capacity_aggregate(self):
        r=self.solve([row(10000)],[row(10000)],10000,10000)
        self.assertLessEqual(r['usedFoodKg']+r['usedWaterKg'],2000+1e-5)
        self.assertEqual(r['vehicleBudgetKg'],2000)

    def test_target_is_not_a_ceiling(self):
        r=self.solve([row(100,50)],[row(100,50)],50,50)
        self.assertAlmostEqual(r['combinedRates'][0],1.)

    def test_unsupported_truck_rejected(self):
        with self.assertRaisesRegex(P1InputError,'2t'):
            optimize_joint_p1([row()],[row()],1,1,.001,.5,1,[{'capacityKg':4000,'count':1}])

    def test_target_not_80_rejected(self):
        food=[row()];food[0]['targetRate']=.9
        with self.assertRaisesRegex(P1InputError,'80%'):
            self.solve(food,[row()],1,1)

    def test_saturated_and_micro_remaining(self):
        r=self.solve([row(10,9.8)],[row(10,9.9)],5,5,delta=.5)
        self.assertIsNone(r['objectiveF1'])
        self.assertEqual(r['allocationsFoodKg'],[0.])
        self.assertEqual(r['microCount'],1)

    def test_more_capacity_allows_more_goods(self):
        f=[row(10000),row(10000)];w=[row(10000),row(10000)]
        a=self.solve(f,w,10000,10000,count=1)
        b=self.solve(f,w,10000,10000,count=2)
        self.assertGreater(sum(b['allocationsFoodKg'])+sum(b['allocationsWaterKg']),
                           sum(a['allocationsFoodKg'])+sum(a['allocationsWaterKg']))

    def test_no_trucks_rejected(self):
        with self.assertRaises(P1InputError):
            self.solve([row()],[row()],10,10,count=0)

if __name__=='__main__':unittest.main()
