"""v49: budgeted, directed Google travel-time matrix and P2 integration."""
import io
import json
import unittest
from unittest.mock import patch
from google_road_matrix import road_time_matrix, matrix_configuration
from p2_kit_optimizer import HUBS, time_matrix, optimize_p2_kit

COORDS = HUBS + [{'lat':34.79,'lng':135.54}]

class _Resp:
    def __init__(self, payload): self.payload=json.dumps(payload).encode()
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self):return self.payload

class V49RoadMatrix(unittest.TestCase):
    def test_disabled_without_paid_api_opt_in(self):
        self.assertFalse(matrix_configuration(100,{'GOOGLE_ROUTES_SERVER_API_KEY':'abc'})['ready'])
        self.assertFalse(matrix_configuration(100,{'GOOGLE_ROAD_MATRIX_ENABLED':'1','GOOGLE_ROUTES_SERVER_API_KEY':'abc'})['ready'])
        self.assertFalse(matrix_configuration(100,{'GOOGLE_ROAD_MATRIX_ENABLED':'1','GOOGLE_ROUTES_SERVER_API_KEY':'abc','GOOGLE_MATRIX_MAX_ELEMENTS':'1000'})['ready'])
    def test_elements_budget_zero_means_no_request(self):
        def cannot_call(*args,**kwargs):self.fail('Network request made without approval')
        m,msg=road_time_matrix(COORDS,requester=cannot_call,environ={'GOOGLE_ROAD_MATRIX_ENABLED':'1','GOOGLE_ROUTES_SERVER_API_KEY':'abc'})
        self.assertIsNone(m)
        self.assertIn('上限',msg)
    def test_matrix_directed_and_complete(self):
        calls=[]
        def requester(req, timeout):
            body=json.loads(req.data)
            assert req.get_header('X-goog-fieldmask') or req.get_header('X-Goog-FieldMask')
            calls.append(body)
            n=len(body['origins'])
            return _Resp([{'originIndex':i,'destinationIndex':j,'status':{},'condition':'ROUTE_EXISTS',
                'duration':f'{(i*10+j)*60}s','distanceMeters':100} for i in range(n) for j in range(n)])
        env={'GOOGLE_ROAD_MATRIX_ENABLED':'1','GOOGLE_ROUTES_SERVER_API_KEY':'test','GOOGLE_MATRIX_MAX_ELEMENTS':'9'}
        m,msg=road_time_matrix(COORDS,requester=requester,environ=env)
        self.assertEqual(len(calls),1)
        self.assertIn('Google',msg)
        self.assertEqual(m[1][2],12.)
        self.assertEqual(m[2][1],21.)
    def test_unreachable_arc_never_blended_with_approximation(self):
        def requester(req,timeout):
            return _Resp([{'originIndex':i,'destinationIndex':j,'status':{},
              'condition':'ROUTE_NOT_FOUND' if (i,j)==(0,2) else 'ROUTE_EXISTS',
              'duration':'180s'} for i in range(3) for j in range(3)])
        env={'GOOGLE_ROAD_MATRIX_ENABLED':'1','GOOGLE_ROUTES_SERVER_API_KEY':'test','GOOGLE_MATRIX_MAX_ELEMENTS':'9'}
        m,msg=road_time_matrix(COORDS,requester=requester,environ=env)
        self.assertIsNone(m)
        self.assertIn('不可',msg)
    def test_optimizer_uses_supplied_directions_for_schedule(self):
        payload={'shelters':[{'name':'A','lat':34.792,'lng':135.541,'demandKits':60,'stockKits':0,'visited':False}],
                 'totalKits':60,'truckCount':1,'maxRounds':1,'minKits':10,'rho':.001,'targetRate':.8}
        baseline=optimize_p2_kit(payload)
        injected=[[0,15,40],[15,0,20],[40,20,0]]
        result=optimize_p2_kit(payload,driving_matrix=injected,matrix_source='google-routes-traffic-aware')
        self.assertNotEqual(result['f2Minutes'],baseline['f2Minutes'])
        self.assertEqual(result['roadTimeSource'],'google-routes-traffic-aware')
        self.assertEqual(result['routes'][0]['stops'][0]['name'],'A')
        self.assertGreater(result['f2Minutes'],baseline['f2Minutes'])
    def test_p0_remains_unconnected(self):
        from pathlib import Path
        src=(Path(__file__).resolve().parents[1]/'app.py').read_text()
        self.assertIn('P0は後続段階で実装します。',src)
        self.assertIn('501',src)

if __name__=='__main__':unittest.main()
