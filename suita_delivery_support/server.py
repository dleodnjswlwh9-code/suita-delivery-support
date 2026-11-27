"""Small WSGI service; compatible with Gunicorn and Python's local server."""
import csv, json, copy, threading, time, uuid, traceback, os
from pathlib import Path
from wsgiref.simple_server import make_server
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer
from .model import defaults, solve, num, recommend
ROOT=Path(__file__).parent; JOBS={}; LOCK=threading.Lock()

def reference():
    result={}
    for folder in sorted((ROOT/'reference').iterdir()):
        if not folder.is_dir():continue
        files={}
        for f in folder.glob('*.csv'):
            with f.open(encoding='utf-8-sig') as stream:files[f.stem]=list(csv.DictReader(stream))
        result[folder.name]=files
    return result

def _worker(key,state):
    try:
        result=solve(state)
        # verify JSON serialization before returning
        json.dumps(result,allow_nan=False)
        with LOCK:JOBS[key].update(status='done',result=result)
    except Exception as exc:
        traceback.print_exc()
        with LOCK:JOBS[key].update(status='error',error=str(exc))

def launch(state):
    if not isinstance(state,dict):raise ValueError('入力条件を確認してください。')
    with LOCK:
        for k,j in list(JOBS.items()):
            if time.monotonic()-j['time']>3600 and j['status']!='working':del JOBS[k]
        if any(j['status']=='working' for j in JOBS.values()):raise ValueError('別の計算を実行中です。')
        if len(JOBS)>=30:
            del JOBS[min(JOBS,key=lambda k:JOBS[k]['time'])]
        key=uuid.uuid4().hex;JOBS[key]=dict(status='working',time=time.monotonic(),state=copy.deepcopy(state),advanced=False)
    threading.Thread(target=_worker,args=(key,copy.deepcopy(state)),daemon=True).start()
    return {'job':key,'status':'working'}

def advance(body):
    key=body['job']
    with LOCK:
        job=JOBS.get(key)
        if not job or job['status']!='done':raise ValueError('計算結果を取得できません。再計算してください。')
        if job['advanced']:raise ValueError('この配送回は確定済みです。')
        result=job['result'];state=copy.deepcopy(job['state']);pid=num(body['id'],'計画ID',1,1000,True);plan=next((x for x in result['front'] if x['id']==pid),None)
        if plan is None:raise ValueError('配送計画を選択してください。')
        now=result['round'];allowed={};hubs={}
        for r in plan['routes']:
            if r['round']==now:
                for q in r['stops']:
                    k=str(q['id']);allowed[k]=q['qty'];hubs[k]=r['hub']
        actual=body['actual'];supp=body['replenishment'];
        if set(actual)!=set(allowed) or len(supp)!=len(state['hubs']):raise ValueError('実績・補給量を確認してください。')
        quantities={k:num(v,'実配送量',0,allowed[k],True) for k,v in actual.items()}; added=[num(v,'追加補給量',0,10000000,True) for v in supp]; used=[0]*len(added)
        minutes=num(body['minutes'],'実所要時間',0,100000)
        before={str(r['id']):r['received'] for r in state['shelters']}
        for row in state['shelters']:
            k=str(row['id']);q=quantities.get(k,0)
            if q:
                if q>max(0,row['demand']-row['received']):raise ValueError('需要を超える実配送量です。')
                row['received']+=q;row['visited']=True;used[hubs[k]]+=q
        for i,h in enumerate(state['hubs']):
            if used[i]>h['stock']:raise ValueError('拠点の在庫不足です。')
            h['stock']+=added[i]-used[i]
        state['history'].append(dict(round=now,plan=pid,planned=sum(allowed.values()),actual=sum(quantities.values()),minutes=minutes,replenishment=sum(added),byHub=used,beforeReceived=before,received={str(r['id']):r['received'] for r in state['shelters']},visited={str(r['id']):r['visited'] for r in state['shelters']},stock=sum(h['stock'] for h in state['hubs'])))
        state['round']+=1;state['rounds']-=1
        if state['mode']=='city':state['maxTotalMinutes']=max(0,state['maxTotalMinutes']-minutes)
        job['advanced']=True
        return state

def app(env,start):
    path=env.get('PATH_INFO','/');method=env.get('REQUEST_METHOD','GET')
    def respond(data,status='200 OK',mime='application/json; charset=utf-8'):
        if mime.startswith('application/json'):data=json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
        start(status,[('Content-Type',mime),('Content-Length',str(len(data))),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff')]);return [data]
    try:
        if method=='GET':
            if path in ('/','/allocation','/p0','/plan','/routes','/results','/model-validation','/rev27-lab','/data'):
                return respond((ROOT/'static/index.html').read_bytes(),mime='text/html; charset=utf-8')
            if path=='/static/app.js':return respond((ROOT/'static/app.js').read_bytes(),mime='application/javascript; charset=utf-8')
            if path=='/static/style.css':return respond((ROOT/'static/style.css').read_bytes(),mime='text/css; charset=utf-8')
            if path.startswith('/api/default/'):
                mode=path.split('/')[-1];return respond(defaults(mode))
            if path=='/api/reference':return respond(reference())
            if path.startswith('/api/job/'):
                with LOCK:
                    j=JOBS.get(path.split('/')[-1]);return respond({k:v for k,v in j.items() if k in ('status','result','error','advanced')} if j else {'error':'結果が失効しました。再計算してください。'},'200 OK' if j else '404 Not Found')
        elif method=='POST':
            length=int(env.get('CONTENT_LENGTH') or 0)
            if length>2000000:raise ValueError('入力データが大きすぎます。')
            body=json.loads(env['wsgi.input'].read(length))
            if path=='/api/solve':return respond(launch(body),'202 Accepted')
            if path=='/api/advance':return respond(advance(body))
            if path=='/api/recommend':
                key=body['job'];j=JOBS.get(key)
                if not j or j['status']!='done':raise ValueError('結果がありません。')
                return respond({'recommended':recommend(j['result']['front'],body['rule'],num(body['extra'],'追加時間',0,10000),num(body['limit'],'F3上限',0,1e9))})
        return respond({'error':'Not found'},'404 Not Found')
    except (ValueError,KeyError,TypeError) as e:return respond({'error':str(e)},'422 Unprocessable Entity')
    except Exception as e:
        traceback.print_exc();return respond({'error':'サーバー処理に失敗しました。'},'500 Internal Server Error')

class ThreadedServer(ThreadingMixIn,WSGIServer):daemon_threads=True

def main():
    port=int(os.environ.get('PORT','8000'));print(f'http://127.0.0.1:{port}',flush=True)
    with make_server('0.0.0.0',port,app,server_class=ThreadedServer) as httpd:httpd.serve_forever()
if __name__=='__main__':main()
