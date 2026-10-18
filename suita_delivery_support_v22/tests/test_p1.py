"""Run from project root: python -m unittest discover -s tests -v"""
import unittest
from p1_optimizer import solve_p1, P1InputError

class P1Tests(unittest.TestCase):
    def test_professor_two_shelters(self):
        rows = [{'demandKg':100,'securedKg':10,'targetRate':.5} for _ in range(2)]
        out = solve_p1(rows, 10, .1)
        self.assertAlmostEqual(out['allocationsKg'][0],5,places=6)
        self.assertAlmostEqual(out['allocationsKg'][1],5,places=6)
        self.assertAlmostEqual(out['objectiveF1'],.84,places=6)
    def test_budget_and_demand(self):
        rows=[{'demandKg':100,'securedKg':30,'targetRate':.7},
              {'demandKg':100,'securedKg':40,'targetRate':.8}]
        out=solve_p1(rows, 20, .01)
        self.assertAlmostEqual(sum(out['allocationsKg']),20,places=5)
        self.assertTrue(all(0<=v<=70 for v in out['allocationsKg']))
    def test_reject_100_percent_goal(self):
        with self.assertRaises(P1InputError):
            solve_p1([{'demandKg':100,'securedKg':0,'targetRate':1}],20,.01)
    def test_no_shortage(self):
        out=solve_p1([{'demandKg':10,'securedKg':100,'targetRate':.7}],50,.01)
        self.assertEqual(out['usedKg'],0)

if __name__=='__main__': unittest.main()
