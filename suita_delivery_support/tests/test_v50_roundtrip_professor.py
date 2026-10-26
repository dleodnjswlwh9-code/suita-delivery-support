"""v50 regressions: complete hub -> all shelters -> SAME hub itineraries.

F2's operation-completion clock is defined at truck return, never at the
last shelter. This verifies asymmetric directed Google-time matrices too.
"""
import unittest
from pathlib import Path
from p2_kit_optimizer import (route_drive, route_drive_breakdown, insert_best,
                              allocate_trucks, optimize_p2_kit, LOADING_MIN,
                              PREP_MIN, UNLOADING_MIN_PER_KIT)

class RoundTripRegression(unittest.TestCase):
    def test_directed_return_arc_explicit(self):
        # Indices 0,1 are hubs; 2,3 are shelters A,B.
        matrix=[[0,0,4,11],[0,0,6,12],[21,10,0,5],[33,15,7,0]]
        out,home=route_drive_breakdown([0,1],0,matrix)
        self.assertEqual(out,9)  # 0->A (4), A->B (5)
        self.assertEqual(home,33)  # B->hub0
        self.assertEqual(route_drive([0,1],0,matrix),42)
        self.assertEqual(route_drive([],0,matrix),0)

    def test_insertion_considers_homeward_arc(self):
        mat=[[0,0,5,10],[0,0,5,10],[1,1,0,5],[100,100,10,0]]
        route={'stops':[1],'hub':0}
        inc,pos=insert_best(route,0,mat)
        self.assertEqual(pos,1)  # hub->B->A->hub = 10+10+1
        self.assertEqual(route_drive([1,0],0,mat),21)
        self.assertEqual(route_drive([0,1],0,mat),110)

    def test_single_truck_hub_assignment_uses_return(self):
        # Nearest in outbound distance is hub 0, but round-trip is hub 1.
        mat=[[0,0,1],[0,0,20],[100,20,0]]
        clean={'trucks':1,'rounds':1,'rows':[{'name':'A'}]}
        assigned,counts=allocate_trucks(clean,[10],mat)
        self.assertEqual(assigned,[1])
        self.assertEqual(counts,[0,1])

    def test_f2_includes_return_to_same_hub(self):
        payload={'shelters':[{'name':'A','lat':34.792,'lng':135.541,
                  'demandKits':60,'stockKits':0,'visited':False}],
                 'totalKits':60,'truckCount':1,'maxRounds':1,'minKits':10,
                 'rho':.001,'targetRate':.8}
        # North round-trip: 12 out + 21 back. South roundtrip: 30 + 11.
        mat=[[0,10,12],[10,0,30],[21,11,0]]
        result=optimize_p2_kit(payload,driving_matrix=mat,matrix_source='google-routes-traffic-aware')
        rt=result['routes'][0]
        self.assertEqual(rt['hub'],0)
        self.assertAlmostEqual(rt['outboundDriveMin'],12)
        self.assertAlmostEqual(rt['returnDriveMin'],21)
        self.assertEqual(rt['routeClosure'],'hub-to-hub')
        self.assertAlmostEqual(rt['totalDriveMin'],33)
        self.assertAlmostEqual(rt['handlingMin'],LOADING_MIN+PREP_MIN+60*UNLOADING_MIN_PER_KIT)
        self.assertAlmostEqual(rt['timeMin'],80.4)
        self.assertAlmostEqual(result['f2Minutes'],80.4)
        self.assertAlmostEqual(rt['returnToHubMin'],rt['timeMin'])

    def test_browser_does_not_override_p2_stop_order(self):
        code=(Path(__file__).resolve().parents[1]/'templates'/'routes.html').read_text(encoding='utf8')
        self.assertIn('const canOptimize=false;',code)
        self.assertIn('last=seq.length?seq.at(-1).name:hub',code)
        self.assertIn('cached.legs.at(-1).trafficMinutes',code)

if __name__=='__main__':unittest.main()
