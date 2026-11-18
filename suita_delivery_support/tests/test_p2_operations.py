"""P2 operational safety / multiobjective regression tests.

Run from project root:
    python -m unittest discover -s tests -v
"""
import copy
import unittest

from kit_planning import KitInputError, clean_input, solve_p0
from p1_kit_optimizer import optimize_p1_kits
from p2_kit_optimizer import (
    optimize_p2_kit, select_pareto_candidate, validate_plan,
)
from tests.test_v2 import mini


class TestP2OperationalConstraints(unittest.TestCase):
    def test_visit_limit_rejected_and_configurable(self):
        shelters = [dict(name=f'施設{i+1}',lat=34.80275 + .00002*i,
                         lng=135.53815 + .00002*i,demandKits=100,
                         stockKits=0,visited=False) for i in range(16)]
        data = dict(shelters=shelters,totalKits=48,targetRate=.8,rho=.001,
                    minKits=3,maxRounds=1,truckCount=1,
                    vehicles=[{'capacityKg':2000,'count':1}],
                    hubStockKits=[48,0],
                    vehicleHubCounts=[{'2t':1,'4t':0},{'2t':0,'4t':0}],
                    maxRoundMinutes=360,maxTotalMinutes=1080,
                    loadingParallel=[1,1],visitWindows={},roadMode='all',
                    p1MinimumKg=13.5,p1MaxRounds=1,
                    p1MandatoryVisitPolicy='professor',p1ModelMode='basic',
                    maxStopsPerRoute=8)
        clean=clean_input(data)
        route=dict(round_=1,truck=1,hub=0,stops=list(range(16)),
                   quantities={i:3 for i in range(16)},load=48,
                   capacityKits=444,vehicleType='2t')
        route['round']=route.pop('round_')
        with self.assertRaises(KitInputError):
            validate_plan(clean,[[route]],[3]*16)
        self.assertFalse(optimize_p1_kits(data,clean=clean,p0=solve_p0(clean))['feasible'])
        data['maxStopsPerRoute']=16
        validate_plan(clean_input(data),[[route]],[3]*16)

    def test_epsilon_constraint_and_dominated_plan(self):
        plans=[dict(f2=80.,f3=9.,f1=1.,method='fast',secondary=(80.,0,1)),
               dict(f2=100.,f3=8.,f1=1.,method='partial',secondary=(100.,1,2)),
               dict(f2=120.,f3=8.,f1=1.,method='dominated',secondary=(120.,2,2))]
        for pct,correct in [(0,'fast'),(10,'fast'),(25,'partial'),(30,'partial')]:
            selected,_,_,_=select_pareto_candidate(plans,pct)
            self.assertEqual(selected['method'],correct)

    def test_fixed_delivery_window_never_relaxes_silently(self):
        data=mini()
        baseline=optimize_p2_kit(data)
        self.assertGreater(baseline['maxFirstSupplyArrivalMin'],1)
        self.assertTrue(baseline['verifiedRouteConstraints'])
        deadline=copy.deepcopy(data)
        deadline['p2MaxFirstSupplyMinutes']=1
        with self.assertRaisesRegex(KitInputError,'初回到着期限'):
            optimize_p2_kit(deadline)

    def test_facility_limit_p1_and_p2(self):
        data=mini();data['maxStopsPerRoute']=2
        clean=clean_input(data)
        p1=optimize_p1_kits(data,clean=clean,p0=solve_p0(clean))
        self.assertTrue(p1['feasible'])
        self.assertTrue(all(len(x['visits'])<=2 for x in p1['assignment']))
        p2=optimize_p2_kit(data,p1_result=p1)
        self.assertLessEqual(p2['peakFacilitiesPerVehicleRound'],2)
        self.assertLessEqual(p2['f2Minutes'],p2['p2F2AllowedMinutes']+.01)
        self.assertFalse(p2['isGloballyOptimal'])
        self.assertTrue(p2['verifiedRouteConstraints'])


if __name__=='__main__':
    unittest.main()
