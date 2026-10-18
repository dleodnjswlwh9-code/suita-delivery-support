"""Regression tests for original aspiration-unbounded P1 behavior."""
import unittest
from p1_full_constraints import optimize_joint_p1

def row(d,b,a,visited=True):
    return dict(demandKg=d,securedKg=b,targetRate=a,visited=visited)

class OriginalPaperP1Tests(unittest.TestCase):
    def runp1(self,food,water,food_kg,water_kg,rho=.01,delta=.5,capacity=10000):
        return optimize_joint_p1(food,water,food_kg,water_kg,rho,delta,1,[{'capacityKg':capacity,'count':1}])

    def test_aspiration_is_not_a_cap(self):
        out=self.runp1([row(100,50,.7)],[row(100,100,.7)],50,0)
        self.assertAlmostEqual(out['allocationsFoodKg'][0],50)
        self.assertAlmostEqual(out['allocationsWaterKg'][0],0)
        self.assertGreater((50+out['allocationsFoodKg'][0])/100,.7)

    def test_negative_theta_allowed(self):
        out=self.runp1([row(100,60,.5)],[row(100,100,.5)],40,0,rho=.1)
        self.assertAlmostEqual(out['thetaByCommodity']['food'],-1)
        self.assertAlmostEqual(out['objectiveByCommodity']['food'],-1.1)

    def test_paper_example(self):
        out=self.runp1([row(100,10,.5),row(100,10,.5)],
                      [row(100,100,.5),row(100,100,.5)],10,0,rho=.1,delta=10,capacity=10)
        self.assertAlmostEqual(out['objectiveByCommodity']['food'],.84)
        self.assertAlmostEqual(out['allocationsFoodKg'][0],5)
        self.assertAlmostEqual(out['allocationsFoodKg'][1],5)

    def test_independent_worst_gap_terms_for_each_commodity(self):
        food=[row(100,10,.9),row(100,10,.9)]
        water=[row(100,10,.9),row(100,10,.9)]
        out=self.runp1(food,water,40,40,rho=.0001,capacity=80)
        self.assertAlmostEqual(sum(out['allocationsFoodKg']),40)
        self.assertAlmostEqual(sum(out['allocationsWaterKg']),40)
        self.assertAlmostEqual(sum(out['allocationsFoodKg'])+sum(out['allocationsWaterKg']),80)

if __name__=='__main__':unittest.main()
