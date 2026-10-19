"""Unit checks for extending the paper's scalarization to two necessities."""
import unittest
from p1_full_constraints import optimize_joint_p1

class PaperExtensionTests(unittest.TestCase):
    def test_theta_is_allowed_negative_and_full_coverage_g_is_minus_one(self):
        row=lambda d,b:dict(demandKg=d,securedKg=b,targetRate=.8,visited=True)
        out=optimize_joint_p1([row(100,80)],[row(100,80)],20,20,.001,.5,1,[{'capacityKg':2000,'count':1}])
        self.assertAlmostEqual(out['theta'],-1.)
        self.assertAlmostEqual(out['objectiveF1'],-1.001)

    def test_single_theta_for_food_and_water(self):
        row=lambda d,b:dict(demandKg=d,securedKg=b,targetRate=.8,visited=True)
        out=optimize_joint_p1([row(100,20)],[row(100,0)],0,20,.001,.5,1,[{'capacityKg':2000,'count':1}])
        self.assertAlmostEqual(out['combinedRates'][0],.2)
        self.assertAlmostEqual(out['theta'],3.)

if __name__=='__main__':unittest.main()
