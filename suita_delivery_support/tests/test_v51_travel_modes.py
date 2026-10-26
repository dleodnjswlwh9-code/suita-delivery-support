"""V51 mode-selection regression without requiring Flask in the test runner."""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import flask  # type: ignore
except ModuleNotFoundError:
    fake = types.ModuleType('flask')
    class _Flask:
        def __init__(self,*args,**kwargs):self.logger=types.SimpleNamespace(exception=lambda *a:None)
        def route(self,*args,**kwargs):return lambda fn:fn
        def context_processor(self,fn):return fn
    fake.Flask=_Flask
    fake.jsonify=lambda obj:obj
    fake.render_template=lambda filename,**kwargs:filename
    fake.request=types.SimpleNamespace(content_length=0,get_json=lambda silent=True:{})
    sys.modules['flask']=fake

import app

PAYLOAD={'shelters':[{'name':'A','lat':34.792,'lng':135.541,'demandKits':60,'stockKits':0,'visited':False}],
 'totalKits':60,'truckCount':1,'maxRounds':1,'minKits':10,'rho':.001,'targetRate':.8,'roadMode':'all'}

class V51TravelModes(unittest.TestCase):
 def run_p2(self,mode):
  with patch.object(app,'request',types.SimpleNamespace(content_length=0,get_json=lambda silent=True:{**PAYLOAD,'travelTimeMode':mode})),\
       patch.object(app,'jsonify',lambda x:x):
   result=app.p2_kits()
  return result if isinstance(result,tuple) else (result,200)
 def test_fixed_does_not_call_paid_matrix(self):
  with patch.object(app,'road_time_matrix',side_effect=AssertionError('Paid request not allowed')):
   r,status=self.run_p2('fixed')
  self.assertEqual(status,200,r)
  self.assertEqual(r['roadTimeSource'],'manhattan-20kmh')
 def test_google_requires_config_instead_of_silent_fallback(self):
  with patch.object(app,'matrix_configuration',return_value={'ready':False,'reason':'key missing'}),\
       patch.object(app,'road_time_matrix',side_effect=AssertionError('Paid request not allowed')):
   r,status=self.run_p2('google')
  self.assertEqual(status,422,r)
  self.assertIn('key missing',r['error'])
 def test_google_injects_directed_matrix_into_solver(self):
  matrix=[[0,15,40],[15,0,20],[40,20,0]]
  with patch.object(app,'matrix_configuration',return_value={'ready':True}),\
       patch.object(app,'road_time_matrix',return_value=(matrix,'Google test')):
   r,status=self.run_p2('google')
  self.assertEqual(status,200,r)
  self.assertEqual(r['roadTimeSource'],'google-routes-traffic-aware')
  self.assertAlmostEqual(r['routes'][0]['returnDriveMin'],matrix[2][r['routes'][0]['hub']])
 def test_google_failure_is_error_not_fixed_mode(self):
  with patch.object(app,'matrix_configuration',return_value={'ready':True}),\
       patch.object(app,'road_time_matrix',return_value=(None,'429 quota exceeded')):
   r,status=self.run_p2('google')
  self.assertEqual(status,422)
  self.assertIn('429',r['error'])
 def test_mode_validation(self):
  r,status=self.run_p2('invalid')
  self.assertEqual(status,422)
 def test_large_google_job_returns_progress_without_waiting_for_http(self):
  data={**PAYLOAD,'shelters':[{'name':f'S{i}','lat':34.70+i*.001,'lng':135.50+i*.0005,
      'demandKits':20,'stockKits':0,'visited':False} for i in range(41)],
      'totalKits':500,'truckCount':10,'maxRounds':8,'minKits':10,'travelTimeMode':'google'}
  class StubThread:
   def __init__(self,*args,**kwargs):self.args=args
   def start(self):pass
  with patch.object(app,'request',types.SimpleNamespace(content_length=0,get_json=lambda silent=True:data)),\
       patch.object(app,'jsonify',lambda x:x),\
       patch.object(app,'matrix_configuration',return_value={'ready':True}),\
       patch.object(app.threading,'Thread',StubThread):
   response,status=app.p2_kits()
  self.assertEqual(status,202,response)
  self.assertRegex(response['jobId'],r'^[0-9a-f]{32}$')
  with patch.object(app,'jsonify',lambda x:x):
   state=app.p2_job_status(response['jobId'])
  self.assertEqual(state['status'],'working')
  app.P2_JOBS.pop(response['jobId'],None)
 def test_web_selection_and_sync_present(self):
  root=Path(__file__).resolve().parents[1]
  routes=(root/'templates/routes.html').read_text()
  plan=(root/'templates/plan.html').read_text()
  self.assertIn('id="p2-travel-time-mode"',routes)
  self.assertIn('走行時間',routes)
  self.assertIn('syncAllocationForDeliverySettings(allocation,settings)',plan)
  self.assertIn('p1_sync.js',plan)
  self.assertNotIn("sessionStorage.removeItem('allocationPlan')",plan)

if __name__=='__main__':unittest.main()
