"""v39 regression: distribution of fulfillment levels isn't hard-coded to two."""
import unittest
from kit_planning import clean_input, solve_p1, round_integer_p1, KitInputError, f1_score


def case(total=12, target=.8, delta=1):
    # Three unsaturated shelters start at differing rates; one is already full.
    return dict(targetRate=target, rho=.001, totalKits=total,
                truckCount=2, maxRounds=2, minKits=delta,
                shelters=[dict(name=f'避難所{i}',lat=34.75+i*.004,
                               lng=135.5+i*.006,demandKits=100,stockKits=b)
                          for i,b in enumerate([0,30,80,100])])

class V39P1Checks(unittest.TestCase):
    def test_more_than_two_rates_are_mathematically_allowed(self):
        cleaned=clean_input(case())
        p1=solve_p1(cleaned)
        rates={round(min(1,(r['stock']+q)/r['demand']),6)
               for r,q in zip(cleaned['rows'],p1['allocations'])}
        self.assertGreaterEqual(len(rates),3)
        self.assertAlmostEqual(p1['f1'],f1_score(cleaned['rows'],p1['allocations'],cleaned['a'],cleaned['rho'],cleaned['delta']))
    def test_selected_aspiration_controls_normalization(self):
        for a,expected in [(0.7,10/3),(0.8,5),(0.9,10)]:
            with self.subTest(a=a):
                self.assertAlmostEqual(1/(1-a), expected)
                cleaned=clean_input(case(target=a))
                p=solve_p1(cleaned)
                self.assertAlmostEqual(p['f1'], f1_score(cleaned['rows'],p['allocations'],a,cleaned['rho'],cleaned['delta']))
    def test_uniform_aspiration_changes_f1_but_not_allocations(self):
        plans=[];scores=[]
        for a in (0.7,0.8,0.9):
            clean=clean_input(case(total=12,target=a))
            sol=solve_p1(clean)
            plans.append(sol['allocations']);scores.append(sol['f1'])
        for plan in plans[1:]:
            self.assertLess(max(abs(a-b) for a,b in zip(plans[0],plan)),1e-7)
        self.assertEqual(len(set(round(v,6) for v in scores)),3)

    def test_fractional_kits_rejected_not_silently_truncated(self):
        d=case(total=100.5)
        with self.assertRaisesRegex(KitInputError,'整数'):
            clean_input(d)
        d=case();d['shelters'][0]['stockKits']=3.5
        with self.assertRaisesRegex(KitInputError,'整数'):
            clean_input(d)
    def test_integer_allocation_reuses_minimum_delivery_constraints(self):
        c=clean_input(case(total=35,delta=10))
        p=solve_p1(c)
        x=round_integer_p1(c,p)
        self.assertTrue(all(z==0 or z>=10 for z in x))
        self.assertTrue(sum(x)<=35)

if __name__=='__main__':unittest.main()
