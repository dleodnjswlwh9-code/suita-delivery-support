"""v23.4 full P1 constraints, shared fleet and two goods.

Run: python -m unittest discover -s tests -v
"""
import unittest
from p1_full_constraints import optimize_joint_p1
from p1_optimizer import P1InputError


def rows(count, demand=100, already=0, target=.7, visited=False):
    return [dict(demandKg=demand, securedKg=already, targetRate=target, visited=visited) for _ in range(count)]

class P1Tests(unittest.TestCase):
    def solve(self, f, w, fs, ws, delta=.5, rounds=1, vehicles=None, rho=.001):
        return optimize_joint_p1(f,w,fs,ws,rho,delta,rounds,
                                 vehicles or [{'capacityKg':2000,'count':1}])

    def test_professor_ideal_five_five_with_two_commodity_extension(self):
        f=rows(2, already=10,target=.5,visited=True)
        # Fully secured second commodity contributes two constant -1 terms
        # to the JOINT F1 augmentation, unlike professor's one-good F1=.84.
        w=rows(2, already=100,target=.5,visited=True)
        answer=self.solve(f,w,10,0,delta=10,vehicles=[{'capacityKg':10,'count':1}],rho=.1)
        self.assertAlmostEqual(answer['allocationsFoodKg'][0],5)
        self.assertAlmostEqual(answer['allocationsFoodKg'][1],5)
        self.assertAlmostEqual(answer['objectiveF1'],.84)
        self.assertAlmostEqual(answer['objectiveByCommodity']['food'],.84)

    def test_mandatory_lower_bound(self):
        r=self.solve(rows(2),rows(2),3,3,delta=2,vehicles=[{'capacityKg':5,'count':1}])
        self.assertEqual(r['mandatoryCount'],2)
        for a,b in zip(r['allocationsFoodKg'],r['allocationsWaterKg']):
            self.assertGreaterEqual(a+b,2-1e-6)

    def test_mandatory_inventory_shortage(self):
        with self.assertRaisesRegex(P1InputError,'最低配送量'):
            self.solve(rows(2),rows(2),1,1,delta=2,vehicles=[{'capacityKg':5,'count':1}])

    def test_insufficient_visit_slots(self):
        with self.assertRaisesRegex(P1InputError,'訪問可能枠'):
            self.solve(rows(3),rows(3),9,9,delta=3,vehicles=[{'capacityKg':5,'count':1}])

    def test_shared_vehicle_capacity(self):
        out=self.solve(rows(2),rows(2),300,300,delta=1,
                       vehicles=[{'capacityKg':30,'count':1}])
        self.assertAlmostEqual(out['usedFoodKg']+out['usedWaterKg'],30,places=6)

    def test_round_budget(self):
        out=self.solve(rows(2),rows(2),300,300,delta=1,rounds=2,
                       vehicles=[{'capacityKg':30,'count':1}])
        self.assertAlmostEqual(out['usedFoodKg']+out['usedWaterKg'],60,places=6)

    def test_shelter_max_per_round(self):
        out=self.solve(rows(1,demand=1000,visited=True),rows(1,demand=1000,visited=True),500,500,
                       delta=1,vehicles=[{'capacityKg':50,'count':5}])
        self.assertLessEqual(sum(out['allocationsFoodKg'])+sum(out['allocationsWaterKg']),50+1e-6)

    def test_micro_remaining_is_frozen(self):
        a=self.solve(rows(1,demand=10,already=9.8,visited=True),
                     rows(1,demand=10,already=9.9,visited=True),5,5,delta=.5)
        self.assertEqual(a['allocationsFoodKg'],[0.0])
        self.assertEqual(a['allocationsWaterKg'],[0.0])
        self.assertIsNone(a['objectiveF1'])

    def test_target_100_percent_rejected(self):
        with self.assertRaises(P1InputError):
            self.solve(rows(1,target=1),rows(1),10,10)

    def test_no_vehicle_rejected(self):
        with self.assertRaisesRegex(P1InputError,'車両が0台'):
            self.solve(rows(1),rows(1),10,10,vehicles=[{'capacityKg':100,'count':0}])

if __name__=='__main__': unittest.main()
