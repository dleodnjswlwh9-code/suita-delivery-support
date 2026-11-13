"""Regression checks for V2 changes, including scenarios not covered by
100-shelter main regression. Run: python -m unittest discover -s tests -v
"""
import copy
import math
import unittest
from kit_planning import clean_input,solve_p1,f1_score,KitInputError
from p0_kit_optimizer import optimize_p0_kits, p0_problem_signature
from p2_kit_optimizer import optimize_p2_kit,validate_plan,schedule_and_check,time_matrix,build_p0_seed_routes
from rolling_actual import confirm_round


def mini():
    # 既訪問施設は追加配送の割当がなくても活性施設として残り得る。
    # 訪問先固定のP0でもθの評価には含める。
    rows=[
        dict(name='試験施設A',lat=34.800,lng=135.539,demandKits=100,stockKits=0,visited=False),
        dict(name='試験施設B',lat=34.799,lng=135.540,demandKits=90,stockKits=5,visited=False),
        dict(name='試験施設C',lat=34.770,lng=135.536,demandKits=80,stockKits=0,visited=False),
        dict(name='試験施設D',lat=34.769,lng=135.537,demandKits=55,stockKits=10,visited=True),
    ]
    return dict(shelters=rows,totalKits=45,targetRate=.8,rho=.001,minKits=3,maxRounds=2,
        truckCount=2,vehicles=[{'capacityKg':2000,'count':2}],
        p0TimeLimitSec=6,p0MipGapPercent=.2,p0MinimumKg=13.5,
        p0MandatoryVisitPolicy='professor',p0ModelMode='basic',
        hubStockKits=[25,20],vehicleHubCounts=[{'2t':1,'4t':0},{'2t':1,'4t':0}],
        maxRoundMinutes=240,maxTotalMinutes=420,loadingParallel=[1,1],
        visitWindows={},roadMode='all',p2DeltaF1=0)

class TestModelV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s=mini();cls.clean=clean_input(cls.s);cls.p1=solve_p1(cls.clean)
        cls.p0=optimize_p0_kits(cls.s,clean=cls.clean,p1=cls.p1)
        if not cls.p0['feasible']:
            raise AssertionError('小規模P0の計算に失敗しました：'+cls.p0.get('reason',''))
        cls.p2=optimize_p2_kit(cls.s,p0_result=cls.p0)

    def test_f1_gap_and_upper_certification(self):
        p0=self.p0
        f1=f1_score(self.clean['rows'],p0['plannedAdditions'],self.clean['a'],self.clean['rho'],self.clean['delta'])
        self.assertAlmostEqual(f1,p0['f1Feasible'],places=5)
        self.assertAlmostEqual(max(0,f1-self.p1['f1']),p0['etaUpperBound'],places=5)
        self.assertLessEqual(p0.get('etaLowerBound') or 0,p0['etaUpperBound']+1e-6)
        self.assertEqual(p0['p0AlgorithmRevision'],83)

    def test_inventory_loads_and_route_times(self):
        p2=self.p2
        self.assertEqual(p2['p2AlgorithmRevision'],83)
        self.assertTrue(p2['verifiedRouteConstraints'])
        self.assertTrue(p2['p0BoundSatisfied'])
        self.assertLessEqual(p2['deliveredKits'],self.s['totalKits'])
        self.assertLessEqual(p2['f2Minutes'],self.s['maxTotalMinutes'])
        self.assertLessEqual(p2['longestRoundMinutes'],self.s['maxRoundMinutes'])
        self.assertEqual(sum(p2['hubOutgoingKits']),p2['deliveredKits'])
        self.assertLessEqual(p2['hubOutgoingKits'][0],25)
        self.assertLessEqual(p2['hubOutgoingKits'][1],20)

    def test_route_recalculation(self):
        seed=build_p0_seed_routes(self.clean,self.p0,time_matrix(self.clean['rows']))
        validate_plan(self.clean,seed[0],seed[3])
        spans,_=schedule_and_check(self.clean,seed[0],seed[1])
        self.assertTrue(sum(spans)<=self.s['maxTotalMinutes'])

    def test_rolling_confirm(self):
        permitted=[0]*len(self.p2['shelters'])
        for rt in self.p2['routes']:
            if rt['round']==1:
                for stop in rt['stops']:permitted[stop['index']]+=stop['kits']
        result=confirm_round(self.p2,1,permitted,actual_minutes=80.)
        self.assertEqual(result['actualKits'],sum(permitted))
        self.assertAlmostEqual(result['remainingTotalMinutes'],self.s['maxTotalMinutes']-80)
        self.assertEqual(sum(result['remainingHubStockKits']),sum(self.s['hubStockKits'])-sum(permitted))

    def test_asymmetric_road_matrix_and_grouping(self):
        s=copy.deepcopy(self.s)
        s['deliveryPoints']=[dict(name='Point-'+str(i//2),lat=r['lat'],lng=r['lng']) for i,r in enumerate(s['shelters'])]
        base=time_matrix(s['shelters']); size=len(base)
        mat=[[float(base[i][j])+(0.17 if i<j and i!=j else 0.) for j in range(size)] for i in range(size)]
        out=optimize_p2_kit(s,driving_matrix=mat,matrix_source='test-asymmetric',p0_result=self.p0)
        self.assertEqual(out['roadTimeSource'],'test-asymmetric')
        self.assertTrue(out['verifiedRouteConstraints'])
        self.assertLessEqual(out['f1Route'],self.p0['f1Feasible']+1e-5)
        self.assertEqual(out['deliveryPointCount'],2)

    def test_reject_unimplemented_road_preference(self):
        s=copy.deepcopy(self.s);s['roadMode']='emergency'
        with self.assertRaises(KitInputError):optimize_p2_kit(s,p0_result=self.p0)

    def test_signature_changes_with_algorithm(self):
        self.assertEqual(len(p0_problem_signature(self.s)),64)
        d=copy.deepcopy(self.s);d['targetRate']=.85
        self.assertNotEqual(p0_problem_signature(self.s),p0_problem_signature(d))

if __name__=='__main__':unittest.main()
