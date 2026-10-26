import math,unittest
from kit_planning import clean_input,solve_p1,f1_score
class P1NormalizationRegression(unittest.TestCase):
    def test_micro_residual_not_in_theta(self):
        data=dict(targetRate=.8,rho=.001,totalKits=200,truckCount=2,maxRounds=1,minKits=10,
                  shelters=[dict(name='A',lat=34.75,lng=135.5,demandKits=17,stockKits=8),
                            dict(name='B',lat=34.76,lng=135.51,demandKits=100,stockKits=20)])
        c=clean_input(data);p=solve_p1(c)
        self.assertAlmostEqual(p['f1'],f1_score(c['rows'],p['allocations'],c['a'],c['rho'],c['delta']),places=8)
        self.assertEqual(p['allocations'][0],0)
        self.assertAlmostEqual(p['theta'],5*(.8-(20+p['allocations'][1])/100),places=7)
    def test_subminimum_rule_changes_when_delta_changes(self):
        d=dict(targetRate=.8,rho=.001,totalKits=100,truckCount=2,maxRounds=2,minKits=10,
               shelters=[dict(name='A',lat=34.75,lng=135.5,demandKits=17,stockKits=8),
                         dict(name='B',lat=34.76,lng=135.51,demandKits=100,stockKits=0)])
        p10=solve_p1(clean_input(d))
        self.assertEqual(p10['allocations'][0],0)
        d['minKits']=1
        p1=solve_p1(clean_input(d))
        self.assertGreater(p1['allocations'][0],0)
if __name__=='__main__':unittest.main()
