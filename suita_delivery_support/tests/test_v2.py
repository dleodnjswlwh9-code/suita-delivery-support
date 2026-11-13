"""Regression checks for V2 changes, including scenarios not covered by
100-shelter main regression. Run: python -m unittest discover -s tests -v
"""
import copy
import math
import unittest
from kit_planning import clean_input,solve_p0,f1_score,KitInputError
from p1_kit_optimizer import optimize_p1_kits, p1_problem_signature
from p2_kit_optimizer import optimize_p2_kit,validate_plan,schedule_and_check,time_matrix,build_p1_seed_routes
from rolling_actual import confirm_round


def mini():
    # 既訪問施設は追加配送の割当がなくても活性施設として残り得る。
    # 訪問先固定のP1でもθの評価には含める。
    rows=[
        dict(name='試験施設A',lat=34.800,lng=135.539,demandKits=100,stockKits=0,visited=False),
        dict(name='試験施設B',lat=34.799,lng=135.540,demandKits=90,stockKits=5,visited=False),
        dict(name='試験施設C',lat=34.770,lng=135.536,demandKits=80,stockKits=0,visited=False),
        dict(name='試験施設D',lat=34.769,lng=135.537,demandKits=55,stockKits=10,visited=True),
    ]
    return dict(shelters=rows,totalKits=45,targetRate=.8,rho=.001,minKits=3,maxRounds=2,
        truckCount=2,vehicles=[{'capacityKg':2000,'count':2}],
        p1TimeLimitSec=6,p1MipGapPercent=.2,p1MinimumKg=13.5,
        p1MandatoryVisitPolicy='professor',p1ModelMode='basic',
        hubStockKits=[25,20],vehicleHubCounts=[{'2t':1,'4t':0},{'2t':1,'4t':0}],
        maxRoundMinutes=240,maxTotalMinutes=420,loadingParallel=[1,1],
        visitWindows={},roadMode='all',p2DeltaF1=0)

class TestModelV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s=mini();cls.clean=clean_input(cls.s);cls.p0=solve_p0(cls.clean)
        cls.p1=optimize_p1_kits(cls.s,clean=cls.clean,p0=cls.p0)
        if not cls.p1['feasible']:
            raise AssertionError('小規模P1の計算に失敗しました：'+cls.p1.get('reason',''))
        cls.p2=optimize_p2_kit(cls.s,p1_result=cls.p1)

    def test_f1_gap_and_upper_certification(self):
        p1=self.p1
        f1=f1_score(self.clean['rows'],p1['plannedAdditions'],self.clean['a'],self.clean['rho'],self.clean['delta'])
        self.assertAlmostEqual(f1,p1['f1Feasible'],places=5)
        self.assertAlmostEqual(max(0,f1-self.p0['f1']),p1['etaUpperBound'],places=5)
        self.assertLessEqual(p1.get('etaLowerBound') or 0,p1['etaUpperBound']+1e-6)
        self.assertEqual(p1['p1AlgorithmRevision'],83)

    def test_swapped_stage_names_preserve_objective_values(self):
        # P0は理想配分、P1は配送制約を考慮した実行可能配分。
        self.assertAlmostEqual(self.p0['f1'], 3.08923076923077, places=5)
        self.assertAlmostEqual(self.p1['f1Star'], self.p0['f1'], places=8)
        self.assertAlmostEqual(self.p1['f1Feasible'], 3.1123089646464654, places=5)
        self.assertAlmostEqual(self.p1['etaUpperBound'], 0.023078195415695557, places=5)
        self.assertAlmostEqual(self.p2['f1Star'], self.p0['f1'], places=8)
        self.assertTrue(self.p2['p1BoundSatisfied'])
        self.assertIn('p1', self.p2)

    def test_inventory_loads_and_route_times(self):
        p2=self.p2
        self.assertEqual(p2['p2AlgorithmRevision'],83)
        self.assertTrue(p2['verifiedRouteConstraints'])
        self.assertTrue(p2['p1BoundSatisfied'])
        self.assertLessEqual(p2['deliveredKits'],self.s['totalKits'])
        self.assertLessEqual(p2['f2Minutes'],self.s['maxTotalMinutes'])
        self.assertLessEqual(p2['longestRoundMinutes'],self.s['maxRoundMinutes'])
        self.assertEqual(sum(p2['hubOutgoingKits']),p2['deliveredKits'])
        self.assertLessEqual(p2['hubOutgoingKits'][0],25)
        self.assertLessEqual(p2['hubOutgoingKits'][1],20)

    def test_route_recalculation(self):
        seed=build_p1_seed_routes(self.clean,self.p1,time_matrix(self.clean['rows']))
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
        out=optimize_p2_kit(s,driving_matrix=mat,matrix_source='test-asymmetric',p1_result=self.p1)
        self.assertEqual(out['roadTimeSource'],'test-asymmetric')
        self.assertTrue(out['verifiedRouteConstraints'])
        self.assertLessEqual(out['f1Route'],self.p1['f1Feasible']+1e-5)
        self.assertEqual(out['deliveryPointCount'],2)

    def test_reject_unimplemented_road_preference(self):
        s=copy.deepcopy(self.s);s['roadMode']='emergency'
        with self.assertRaises(KitInputError):optimize_p2_kit(s,p1_result=self.p1)

    def test_signature_changes_with_algorithm(self):
        self.assertEqual(len(p1_problem_signature(self.s)),64)
        d=copy.deepcopy(self.s);d['targetRate']=.85
        self.assertNotEqual(p1_problem_signature(self.s),p1_problem_signature(d))

if __name__=='__main__':unittest.main()
