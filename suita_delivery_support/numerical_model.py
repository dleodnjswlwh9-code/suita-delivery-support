"""Relief supply planning: rev27 objectives, exact allocation relaxation, audited routing.
City extension: 2 depots with independent stocks; existing shelter stock counts in supply.
No emergency road or disaster presets; no live-road claims.
"""
import math, itertools, random, time, copy, json
from pathlib import Path
import numpy as np
from scipy.optimize import linprog, milp, Bounds, LinearConstraint
from scipy.sparse import coo_matrix
RHO=1e-4
TOL=1e-8
DATA=Path(__file__).parent/'data'

def defaults(mode='city'):
    if mode in ('six','four'):
        if mode=='six':
            coords=[(2,1),(5,1),(1,4),(6,4),(2,7),(7,7)]; d=[30,20,10,10,10,10];g=[1]*6;stock=40;cap=10
        else:
            coords=[(1,2),(4,1),(2,5),(5,4)];d=[20,10,10,10];g=[1,1.5,1,.5];stock=18;cap=6
        return dict(mode=mode,unit='箱',target=.5,delta=0.,keep=True,minVisit=1,rounds=3,round=1,
            speed=20,loading=5,prep=0,unloading=.5,rule='extra',extra=15,f3Limit=10,
            hubs=[dict(name='拠点',x=0,y=0,stock=stock,vehicles=[dict(capacity=cap,count=2)])],
            shelters=[dict(id=i+1,name=f'避難所{i+1}',x=x,y=y,demand=d[i],received=0,visited=False,gamma=g[i],enabled=True) for i,(x,y) in enumerate(coords)],history=[])
    raw=json.loads((DATA/'allocation_shelters.json').read_text()); pop=json.loads((DATA/'regional_population.json').read_text())['regions']
    by={}
    for s in raw:
        key=s['region'].replace('地域','');key='千里ニュータウン' if key.startswith('千里ニュータウン') else key
        by.setdefault(key,[]).append(s)
    demand={}
    for k,rs in by.items():
        vals=np.array([r['capacity'] for r in rs],float);v=pop[k]['initial']*vals/vals.sum();iv=np.floor(v).astype(int)
        for i in sorted(range(len(rs)),key=lambda i:-(v[i]-iv[i]))[:pop[k]['initial']-int(iv.sum())]:iv[i]+=1
        for r,q in zip(rs,iv):demand[r['sourceIndex']]=int(q)
    shelters=[]
    for s in raw:
        st=s['stock'];enabled=st.get('retortRice',0)>0 and st.get('water500ml',0)>0
        shelters.append(dict(id=s['sourceIndex']+1,name=s['name'],region=s['region'],lat=s['lat'],lng=s['lng'],capacity=s['capacity'],demand=demand[s['sourceIndex']],received=min(st.get('retortRice',0)//3,st.get('water500ml',0)//6),visited=False,gamma=1,enabled=enabled))
    hubs=json.loads((DATA/'hubs.json').read_text())
    hubs=[dict(name=h['category'],facility=h['name'],lat=h['lat'],lng=h['lng'],stock=889 if i==0 else 888,loadingSlots=5,vehicles=[dict(capacity=444,count=5),dict(capacity=888,count=4)]) for i,h in enumerate(hubs)]
    return dict(mode='city',unit='人日分',target=.8,delta=0.,keep=True,minVisit=3,rounds=5,round=1,speed=20,loading=30,prep=15,unloading=.04,maxRoundMinutes=360,maxTotalMinutes=1080,maxStops=8,nearbyMeters=200,rule='extra',extra=15,f3Limit=100, hubs=hubs,shelters=shelters,history=[])

def num(x,name,lo,hi,integer=False):
    try: v=float(x)
    except Exception: raise ValueError(name+'：数値を入力してください。')
    if not math.isfinite(v) or not lo<=v<=hi or (integer and v!=int(v)):raise ValueError(f'{name}：{lo}～{hi}の'+('整数' if integer else '数値')+'を入力してください。')
    return int(v) if integer else v

def nearby_groups(rows,threshold):
    """Complete-linkage, shortest eligible edges first, same prior rule.
    Centroids are coordinate representatives, not snapped to roads.
    Each original shelter retains its demand, stock, handling, and visit constraint.
    """
    n=len(rows);coords=np.array([[r['lat'],r['lng']] for r in rows],float)
    dlat=np.deg2rad(coords[:,None,0]-coords[None,:,0]);dlon=np.deg2rad(coords[:,None,1]-coords[None,:,1]);lat=np.deg2rad(coords[:,0]);dist=6371000*2*np.arcsin(np.sqrt(np.clip(np.sin(dlat/2)**2+np.cos(lat[:,None])*np.cos(lat[None,:])*np.sin(dlon/2)**2,0,1)))
    groups=[[i] for i in range(n)]
    if threshold>0:
        for _,i,j in sorted((dist[i,j],i,j) for i in range(n) for j in range(i+1,n) if dist[i,j]<=threshold):
            ai=next(k for k,x in enumerate(groups) if i in x);bi=next(k for k,x in enumerate(groups) if j in x)
            if ai!=bi and max(dist[a,b] for a in groups[ai] for b in groups[bi])<=threshold:
                groups[min(ai,bi)]+=groups.pop(max(ai,bi))
    out=[]
    for i,g in enumerate(groups):
        lat,lng=coords[g].mean(axis=0);name=f'代表点{i+1}' if len(g)>1 else rows[g[0]]['name'];out.append(dict(name=name,lat=float(lat),lng=float(lng),members=[rows[j]['id'] for j in g],memberNames=[rows[j]['name'] for j in g],diameter=float(max((dist[a,b] for a in g for b in g),default=0))))
        for j in g:rows[j].update(pointLat=float(lat),pointLng=float(lng),pointName=name)
    return out

def prepare(s):
    mode=s['mode']; city=mode=='city';unit='人日分' if city else '箱'
    a=num(s['target'],'目標配分率',0,.99);delta=num(s['delta'],'許容幅',0,10);m=num(s['minVisit'],'最小配送量',1,10000,True)
    R=num(s['rounds'],'残りの配送回数',1,10,True); h=num(s['round'],'現在の配送回',1,100,True)
    speed=num(s['speed'],'想定速度',1,120) if city else 20;load=num(s['loading'],'積込時間',0,1000);prep=num(s['prep'],'荷卸準備時間',0,1000);beta=num(s['unloading'],'単位荷卸時間',0,1000)
    if mode not in ('city','six','four'):raise ValueError('対象を確認してください。')
    rows=[dict(x) for x in s['shelters'] if x.get('enabled')];
    if not rows or len(rows)>123:raise ValueError('対象避難所を選んでください。')
    if len(set(r['id'] for r in rows))!=len(rows):raise ValueError('避難所IDが重複しています。')
    for r in rows:
        r['demand']=num(r['demand'],r['name']+'の需要',1,10000000,True);r['received']=num(r['received'],r['name']+'の供給済量',0,10000000,True);r['gamma']=num(r['gamma'],r['name']+'の緊急度',.001,100)
    hubs=copy.deepcopy(s['hubs']);fleet=[]
    if len(hubs)!=(2 if city else 1):raise ValueError('拠点の数を確認してください。')
    for i,hub in enumerate(hubs):
        hub['stock']=num(hub['stock'],'拠点在庫',0,10000000,True)
        hub['loadingSlots']=num(hub.get('loadingSlots',60),'同時積込台数',1,60,True) if city else 60
        for v in hub['vehicles']:
            cap=num(v['capacity'],'車両容量',1,10000,True);count=num(v['count'],'車両数',0,30,True)
            if city and cap not in (444,888):raise ValueError('吹田市は2t・4t車両のみ。')
            for _ in range(count):fleet.append(dict(id=len(fleet)+1,hub=i,cap=cap))
    if not fleet or len(fleet)>60:raise ValueError('車両を1～60台に設定してください。')
    d=np.array([r['demand'] for r in rows],int);rec=np.array([r['received'] for r in rows],int);gamma=np.array([r['gamma'] for r in rows]);rem=np.maximum(0,d-rec);active=rem>=m
    mandatory=active & np.array([not r['visited'] for r in rows]);maxcap=max(v['cap'] for v in fleet)
    hi=np.where(active,np.minimum(rem,R*maxcap),0);lo=mandatory.astype(int)*m
    stock=sum(h['stock'] for h in hubs);budget=min(stock,R*sum(v['cap'] for v in fleet));w=1/(1-a)
    if not np.any(active):raise ValueError('終了：最小配送量を受け取れる避難所がありません。')
    if budget<m or np.any(lo>hi) or lo.sum()>budget or mandatory.sum()>R*sum(v['cap']//m for v in fleet):raise ValueError('必須訪問に必要な在庫・車両枠が不足しています。')
    groups=nearby_groups(rows,num(s.get('nearbyMeters',200),'近接距離',0,2000)) if city else []
    loc=hubs+rows;M=len(hubs);coords=np.array([[r.get('pointLng',r['lng']),r.get('pointLat',r['lat'])] if city else [r['x'],r['y']] for r in loc]);dx=np.abs(coords[:,None,0]-coords[None,:,0]);dy=np.abs(coords[:,None,1]-coords[None,:,1]);
    if city: mat=(dy*111.32+dx*111.32*np.cos(np.deg2rad((coords[:,None,1]+coords[None,:,1])/2)))*60/speed
    else: mat=2*(dx+dy)
    maxround=num(s.get('maxRoundMinutes',360),'1回の時間上限',1,100000) if city else math.inf
    maxtotal=num(s.get('maxTotalMinutes',1080),'累積時間上限',0,100000) if city else math.inf
    maxstops=num(s.get('maxStops',8),'1台1回の訪問上限',1,123,True) if city else 123
    p=dict(groups=groups,maxround=maxround,maxtotal=maxtotal,maxstops=maxstops,s=s,mode=mode,unit=unit,a=a,delta=delta,keep=bool(s['keep']),m=m,R=R,h=h,load=load,prep=prep,beta=beta,rows=rows,hubs=hubs,fleet=fleet,d=d,rec=rec,rem=rem,active=active,mandatory=mandatory,hi=hi,lo=lo,budget=budget,w=w,gamma=gamma,mat=mat,M=M,K=len(rows),T=len(fleet))
    return p

def f1(p,x):
    g=p['w']*(p['a']-(p['rec']+np.asarray(x))/p['d']);return float(max(g[p['active']])+RHO*g.sum())

def shortage(p,rec):return float(np.sum((p['w']*p['gamma']*np.maximum(0,p['a']-rec/p['d']))[p['active']]))

class Model:
    def __init__(self):self.lb=[];self.ub=[];self.int=[];self.rr=[];self.cc=[];self.v=[];self.l=[];self.u=[]
    def var(self,lo=0,hi=np.inf,integer=0):
        i=len(self.lb);self.lb.append(lo);self.ub.append(hi);self.int.append(integer);return i
    def add(self,terms,lo=-np.inf,hi=np.inf):
        r=len(self.l);self.l.append(lo);self.u.append(hi)
        for k,v in terms:
            if v:self.rr.append(r);self.cc.append(int(k));self.v.append(float(v))
    def solve(self,objective,sec=10):
        c=np.zeros(len(self.lb));
        for i,v in objective:c[i]+=v
        A=coo_matrix((self.v,(self.rr,self.cc)),shape=(len(self.l),len(c))).tocsc()
        return milp(c,integrality=np.array(self.int),bounds=Bounds(self.lb,self.ub),constraints=LinearConstraint(A,self.l,self.u),options={'time_limit':sec,'mip_rel_gap':1e-9,'presolve':True})

def alloc(p,integer=False,cap=None,quantity=False,prefer=None,fixed_total=None):
    K=p['K'];w=p['w'];d=p['d'];r=p['rec'];m=Model();x=[m.var(p['lo'][k],p['hi'][k],int(integer)) for k in range(K)];th=m.var(-np.inf,np.inf)
    obj=[(th,1)]+[(x[k],-RHO*w/d[k]) for k in range(K)];const=RHO*np.sum(w*(p['a']-r/d))
    for k in np.flatnonzero(p['active']):m.add([(th,1),(x[k],w/d[k])],lo=w*(p['a']-r[k]/d[k]))
    m.add([(i,1) for i in x],lo=fixed_total if fixed_total is not None else -np.inf,hi=fixed_total if fixed_total is not None else p['budget'])
    if cap is not None:m.add(obj,hi=cap-const+TOL)
    objective=([(i,-1) for i in x] if quantity else obj) if prefer is None else [(i,float(v)) for i,v in zip(x,prefer)]
    if integer: sol=m.solve(objective,sec=5)
    else:
        c=np.zeros(K+1)
        for i,v in objective:c[i]=v
        A=coo_matrix((m.v,(m.rr,m.cc)),shape=(len(m.l),K+1)).toarray();aa=[];bb=[]
        for j in range(len(m.l)):
            if math.isfinite(m.u[j]):aa.append(A[j]);bb.append(m.u[j])
            if math.isfinite(m.l[j]):aa.append(-A[j]);bb.append(-m.l[j])
        sol=linprog(c,A_ub=aa,b_ub=bb,bounds=list(zip(m.lb,m.ub)),method='highs')
    if sol.x is None:return None
    x=np.rint(sol.x[:K]).astype(int) if integer else sol.x[:K]
    return dict(x=x,value=f1(p,x),cert=sol.status==0,dual=getattr(sol,'mip_dual_bound',None))

def trip_time(p,hub,stops,qs):
    if not stops:return 0.
    seq=[hub]+[p['M']+k for k in stops]+[hub];travel=sum(p['mat'][a,b] for a,b in zip(seq,seq[1:]))
    return float(p['load']+p['prep']*len(stops)+p['beta']*sum(qs.values())+travel)

def route_order(p,hub,keys):
    keys=list(keys);mat=p['mat'];M=p['M']
    if len(keys)<=7:
        return list(min(itertools.permutations(keys),key=lambda q:sum(mat[a,b] for a,b in zip([hub]+[M+k for k in q],[M+k for k in q]+[hub])))) if keys else []
    result=[];cur=hub
    while keys:
        k=min(keys,key=lambda k:mat[cur,M+k]);result.append(k);keys.remove(k);cur=M+k
    for _ in range(3):
        changed=False
        for i in range(len(result)-1):
            for j in range(i+1,len(result)):
                a=hub if i==0 else M+result[i-1];b=M+result[i];c=M+result[j];d=hub if j==len(result)-1 else M+result[j+1]
                if mat[a,c]+mat[b,d]+1e-7<mat[a,b]+mat[c,d]:result[i:j+1]=reversed(result[i:j+1]);changed=True
        if not changed:break
    return result

def pack(p,x,variant=0):
    """Construct audited integer vehicle/round assignment; no assumed feasibility."""
    R,T,K,m=p['R'],p['T'],p['K'],p['m'];rng=random.Random(variant+712);x=np.array(x,int)
    if np.any((x>0)&(x<m)):return None
    waves=[[{} for v in p['fleet']] for _ in range(R)];loads=np.zeros((R,T),int);hubstock=[h['stock'] for h in p['hubs']];seen=[set() for _ in range(R)];M=p['M'];mat=p['mat'];gamma=p['gamma']
    keys=list(np.flatnonzero(x>0));
    if variant%4==0:keys.sort(key=lambda k:(-x[k],-gamma[k]))
    elif variant%4==1:keys.sort(key=lambda k:(-gamma[k]/p['d'][k],-x[k]))
    elif variant%4==2:keys.sort(key=lambda k:-min(mat[h,M+k] for h in range(M)))
    else:rng.shuffle(keys)
    for k in keys:
        left=int(x[k]);
        while left:
            options=[]
            for r in range(R):
                if k in seen[r]:continue
                for t,v in enumerate(p['fleet']):
                    h=v['hub'];maxq=min(v['cap']-int(loads[r,t]),hubstock[h],left)
                    if maxq<m:continue
                    q=maxq
                    if 0<left-q<m:q=left-m
                    if q<m:continue
                    old=waves[r][t]
                    if len(old)>=p['maxstops']:continue
                    near=min([mat[h,M+k]]+[mat[M+j,M+k] for j in old]);new_trip=not old
                    # Earlier dispatch, shorter local travel, and different load policies.
                    score= (r*(70 if variant%4==1 else 40)+near*(1 if variant%4!=2 else 2)+new_trip*(3 if variant%4!=2 else 0)+len(old)*(8 if p['mode']=='city' else 1)+loads[r,t]/max(1,v['cap'])*(10 if p['mode']=='city' else 2)-q/max(1,left)*5 + rng.random()*(.1 if variant<4 else 3))
                    options.append((score,r,t,q))
            if not options:return None
            _,r,t,q=min(options);waves[r][t][k]=q;loads[r,t]+=q;seen[r].add(k);hubstock[p['fleet'][t]['hub']]-=q;left-=q
    # Shift empty rounds to the end; maintain order otherwise.
    waves=[w for w in waves if any(w)]+[w for w in waves if not any(w)]
    return waves

def evaluate(p,waves,method='候補探索'):
    R,T,K,m=p['R'],p['T'],p['K'],p['m']; rec=p['rec'].copy(); total=np.zeros(K,int);used=[0]*p['M'];out=[];dur=[];short=[];cum=[];empty=False
    if len(waves)!=R:raise ValueError('配送回数不一致')
    for r,wave in enumerate(waves):
        if len(wave)!=T:raise ValueError('車両数不一致')
        seen=set();times=[];departed=[0]*p['M']
        if any(wave) and empty:raise ValueError('配送回の連続使用制約違反')
        if not any(wave):empty=True
        for t,qs in enumerate(wave):
            v=p['fleet'][t];h=v['hub'];qsum=sum(qs.values())
            if len(qs)>p['maxstops'] or qsum>v['cap'] or any(q<m or q!=int(q) or k in seen for k,q in qs.items()):raise ValueError('車両容量・最小量・同一回訪問制約違反')
            if not qs:continue
            stops=route_order(p,h,qs);minutes=trip_time(p,h,stops,qs)+p['load']*(departed[h]//p['hubs'][h]['loadingSlots']);departed[h]+=1;times.append(minutes);used[h]+=qsum
            for k,q in qs.items():seen.add(k);total[k]+=q;rec[k]+=q
            out.append(dict(round=p['h']+r,truck=v['id'],hub=h,capacity=v['cap'],total=qsum,minutes=round(minutes,5),stops=[dict(index=int(k),id=p['rows'][k]['id'],name=p['rows'][k]['name'],qty=int(qs[k])) for k in stops]))
        dur.append(max(times,default=0.));
        if dur[-1]>p['maxround']+1e-7:raise ValueError('配送回の時間上限違反')
        short.append(shortage(p,rec));cum.append((rec/p['d']).tolist())
    if sum(dur)>p['maxtotal']+1e-7:raise ValueError('累積時間上限違反')
    if any(u>h['stock'] for u,h in zip(used,p['hubs'])) or np.any(total>p['rem']) or np.any(total[p['mandatory']]<m) or not any(waves[0]):raise ValueError('在庫・需要・必須訪問制約違反')
    return dict(method=method,f1=f1(p,total),f2=float(sum(dur)),f3=float(sum(short[:-1])),total=int(total.sum()),allocation=total.tolist(),minRate=float(min(rec/p['d'])),routes=out,roundTimes=dur,shortage=short,coverage=cum,usedByHub=used)

def full_mip(p,cap=None,maximize=False,route=False,keep_total=None,objective='f2',time_cap=None,f3_cap=None,sec=8):
    """Reduced dispatch MILP; optional exact visit-set routing model for small examples."""
    K,T,R=p['K'],p['T'],p['R'];J=T*R;m=p['m'];model=Model();
    # Fairness cap gives safe per-site lower bounds; other sites' smallest signed gaps >= -1 (or already overstocked).
    lo=p['lo'].copy();hi=p['hi'].copy();w=p['w'];d=p['d'];rec=p['rec'];active=p['active']
    if cap is not None:
        gmin=w*(p['a']-(rec+hi)/d);theta_max=cap-RHO*gmin.sum()+TOL
        lo=np.maximum(lo,np.where(active,np.ceil(d*(p['a']-theta_max/w)-rec-1e-7),0).astype(int))
        if keep_total is not None:hi=np.minimum(hi,keep_total-int(lo.sum())+lo)
        if np.any(lo>hi):return None
    n=np.empty((K,J),int);y=np.empty((K,J),int)
    for k in range(K):
        for j in range(J):
            bound=min(hi[k],p['fleet'][j%T]['cap']);n[k,j]=model.var(0,max(0,bound),1);y[k,j]=model.var(0,int(bound>=m),1)
            model.add([(n[k,j],1),(y[k,j],-m)],lo=0);model.add([(n[k,j],1),(y[k,j],-bound)],hi=0)
    theta=model.var(-np.inf,np.inf);u=[model.var(1 if r==0 else 0,1,1) for r in range(R)]
    f1obj=[(theta,1)]+[(n[k,j],-RHO*w/d[k]) for k in range(K) for j in range(J)];const=RHO*sum(w*(p['a']-rec/d));
    for k in range(K):
        model.add([(i,1) for i in n[k]],lo=lo[k],hi=hi[k]);
        if active[k]:model.add([(theta,1)]+[(i,w/d[k]) for i in n[k]],lo=w*(p['a']-rec[k]/d[k]))
    alln=[(i,1) for i in n.flat]
    model.add(alln,lo=keep_total if keep_total is not None else -np.inf,hi=p['budget'])
    if cap is not None:model.add(f1obj,hi=cap-const+TOL)
    for h in range(p['M']):model.add([(n[k,j],1) for k in range(K) for j in range(J) if p['fleet'][j%T]['hub']==h],hi=p['hubs'][h]['stock'])
    H=[model.var() for r in range(R)] if route else []
    f3obj=[]
    for r in range(R):
        js=range(r*T,(r+1)*T)
        if r:model.add([(u[r],1),(u[r-1],-1)],hi=0)
        model.add([(u[r],1)]+[(y[k,j],-1) for k in range(K) for j in js],hi=0)
        for k in range(K):model.add([(y[k,j],1) for j in js],hi=1)
        for j in js:
            v=p['fleet'][j%T];model.add([(y[k,j],1) for k in range(K)],hi=p['maxstops']);model.add([(n[k,j],1) for k in range(K)]+[(u[r],-v['cap'])],hi=0)
            if route:
                sites=[k for k in range(K) if hi[k]>=m and v['cap']>=m];subsets=[()]+[z for zlen in range(1,min(len(sites),v['cap']//m)+1) for z in itertools.combinations(sites,zlen)]
                z=[model.var(0,1,0) for _ in subsets];model.add([(i,1) for i in z],lo=1,hi=1)
                for k in range(K):model.add([(y[k,j],1)]+[(z[i],-1) for i,ss in enumerate(subsets) if k in ss],lo=0,hi=0)
                costs=[trip_time(p,v['hub'],route_order(p,v['hub'],ss),{k:0 for k in ss}) for ss in subsets]
                model.add([(z[i],cost) for i,cost in enumerate(costs)]+[(n[k,j],p['beta']) for k in range(K)]+[(H[r],-1)],hi=0)
            if j%T>0:
                pv=p['fleet'][j%T-1]
                if pv['hub']==v['hub'] and pv['cap']==v['cap']:model.add([(n[k,j],1) for k in range(K)]+[(n[k,j-1],-1) for k in range(K)],hi=0)
        if route and r<R-1:
            for k in np.flatnonzero(active):
                e=model.var(0,max(0,p['a']-rec[k]/d[k]));model.add([(e,1)]+[(n[k,j],1/d[k]) for j in range((r+1)*T)],lo=p['a']-rec[k]/d[k]);f3obj.append((e,w*p['gamma'][k]))
    if route and f3_cap is not None:model.add(f3obj,hi=f3_cap+1e-8)
    if route and time_cap is not None:model.add([(i,1) for i in H],hi=time_cap+1e-7)
    cost=([(i,-1) for i,_ in alln] if maximize else f1obj) if not route else ([(i,1) for i in H] if objective=='f2' else f3obj+[(i,1e-7) for i in H])
    sol=model.solve(cost,sec=sec)
    if sol.x is None:return None
    xx=np.rint(sol.x[n]).astype(int);waves=[[{k:int(xx[k,r*T+t]) for k in range(K) if xx[k,r*T+t]>0} for t in range(T)] for r in range(R)]
    try:plan=evaluate(p,waves,'MILP' if route else '整数配送割当')
    except ValueError:return None
    if cap is not None and plan['f1']>cap+2e-7:return None
    if keep_total is not None and plan['total']<keep_total:return None
    return dict(plan=plan,waves=waves,cert=sol.status==0,solverStatus=int(sol.status),dual=getattr(sol,'mip_dual_bound',None))

def nondominated(plans):
    clean=[]
    for p in sorted(plans,key=lambda x:(x['f2'],x['f3'],x['f1'])):
        if any(abs(p['f2']-q['f2'])<1e-7 and abs(p['f3']-q['f3'])<1e-7 for q in clean):continue
        if not any(q['f2']<=p['f2']+1e-7 and q['f3']<=p['f3']+1e-7 and (q['f2']<p['f2']-1e-7 or q['f3']<p['f3']-1e-7) for q in plans):clean.append(p)
    for i,p in enumerate(clean):p['id']=i+1
    return clean

def recommend(plans,rule='fast',extra=15,f3limit=100):
    if rule=='fast':return min(plans,key=lambda q:(q['f2'],q['f3']))['id']
    if rule=='shortage':return min(plans,key=lambda q:(q['f3'],q['f2']))['id']
    if rule=='extra':
        fastest=min(q['f2'] for q in plans);return min((q for q in plans if q['f2']<=fastest+extra+1e-7),key=lambda q:(q['f3'],q['f2']))['id']
    if rule=='limit':
        valid=[q for q in plans if q['f3']<=f3limit+1e-7];return min(valid,key=lambda q:(q['f2'],q['f3']))['id'] if valid else None
    raise ValueError('推奨基準が不正です。')

def solve(state):
    p=prepare(state);small=p['mode']!='city' and p['K']<=7 and p['T']<=3 and p['R']<=4 and p['M']==1
    ideal=alloc(p);integer=alloc(p,True)
    if ideal is None or integer is None:raise ValueError('配分問題の解を得られませんでした。')
    plans=[];base=None;lower=integer['value'] if integer['cert'] else ideal['value'];
    def add(waves,method):
        if waves is None:return None
        try: plan=evaluate(p,waves,method)
        except ValueError:return None
        plans.append(plan);return plan
    for v in range(12 if small else 8):
        z=add(pack(p,integer['x'],v),'配分・車両割当探索')
        if z is not None and (base is None or z['f1']<base['f1']):base=z
    # For city, exact relaxed optimum is certified if its allocation can actually be packed.
    if base is None or small:
        sol=full_mip(p,sec=8 if small else 15)
        if sol:
            z=sol['plan'];plans.append(z)
            if base is None or z['f1']<base['f1']:base=z
            if sol['cert'] and (small or z['f1']>=lower-1e-7):lower=z['f1']
    if base is None:raise ValueError('計算時間内に実行可能な配送割当を得られませんでした。車両数・在庫・回数を見直してください。')
    p0=base;cert=abs(p0['f1']-lower)<2e-7;cap=p0['f1']+p['delta'];
    maxq=alloc(p,True,cap=cap,quantity=True)
    prime=p0;upper=p['budget']
    if maxq:
        if maxq['cert']:upper=int(maxq['x'].sum())
        for v in range(12 if small else 8):
            q=add(pack(p,maxq['x'],v),'最大配送量候補')
            if q and q['f1']<=cap+2e-7 and q['total']>prime['total']:prime=q
    if prime['total']<upper:
        sol=full_mip(p,cap=cap,maximize=True,sec=8 if small else 12)
        if sol:
            q=sol['plan'];plans.append(q)
            if q['total']>prime['total']:prime=q
            if sol['cert']:upper=q['total']
    required=prime['total'] if p['keep'] else None
    # Alternate allocations inside the same allowed F1 region; real priority/distance inputs affect search.
    proximity=np.min(p['mat'][:p['M'],p['M']:],axis=0)
    prefs=[proximity,-p['gamma']/p['d'],p['gamma']/p['d']]
    for i,cost in enumerate(prefs):
        a=alloc(p,True,cap=cap,prefer=cost,fixed_total=prime['total'])
        if a:
            for v in (0,1,2,5):add(pack(p,a['x'],v),f'配分・経路候補 {i+1}')
    if not p['keep']:
        # Minimise quantity within cap (not a promise of optimal F2), and intermediate quantities.
        a=alloc(p,True,cap=cap,prefer=np.ones(p['K']))
        if a:
            low=int(a['x'].sum());span=prime['total']-low
            for q in sorted(set([low,low+span//2,max(low,prime['total']-1)])):
                b=alloc(p,True,cap=cap,prefer=proximity,fixed_total=q)
                if b:
                    for v in (0,1,2):add(pack(p,b['x'],v),'総量下限なし・少量配送候補')
    exact_note='候補探索（全体最適性未証明）'; exact_fast=False
    if small:
        # Reverse epsilon-constraint search on the discrete duration lattice.
        from fractions import Fraction
        from functools import reduce
        from math import gcd, lcm
        fs=[Fraction(str(x)).limit_denominator(100000) for x in (p['load'],p['prep'],p['beta'],2)]
        den=reduce(lcm,(x.denominator for x in fs),1);step=reduce(gcd,(int(x*den) for x in fs))/den
        first=full_mip(p,cap=cap,route=True,keep_total=required,objective='f2',sec=10)
        if first:
            plans.append(first['plan']);exact_fast=first['cert'];fast=first['plan']['f2']
            tied=full_mip(p,cap=cap,route=True,keep_total=required,objective='f3',time_cap=fast,sec=6)
            if tied:plans.append(tied['plan'])
            last=full_mip(p,cap=cap,route=True,keep_total=required,objective='f3',sec=6)
            cursor=last;deadline=time.monotonic()+28;steps=0
            while cursor and steps<12 and time.monotonic()<deadline:
                q=cursor['plan'];plans.append(q)
                # At equal F3, find the earliest F2; avoid dominated ties.
                early=full_mip(p,cap=cap,route=True,keep_total=required,objective='f2',f3_cap=q['f3'],sec=3)
                if early:
                    plans.append(early['plan']);q=early['plan']
                if q['f2']<=fast+1e-6:break
                cursor=full_mip(p,cap=cap,route=True,keep_total=required,objective='f3',time_cap=q['f2']-max(step,1e-5),sec=4)
                steps+=1
                if cursor and cursor['plan']['f2']>=q['f2']-1e-6:break
            exact_note='小規模MILP＋候補探索（全非劣解の列挙は未証明）'
    allowed=[z for z in plans if z['f1']<=cap+2e-7]
    if allowed:
        found=max(allowed,key=lambda z:z['total'])
        if found['total']>prime['total']:prime=found;upper=max(upper,prime['total'])
    required=prime['total'] if p['keep'] else None
    valid=[z for z in allowed if required is None or z['total']>=required]
    if not valid:raise ValueError('配分評価と総量下限を満たす経路候補を得られませんでした。')
    front=nondominated(valid);rid=recommend(front,state.get('rule','fast'),num(state.get('extra',15),'追加時間',0,10000),num(state.get('f3Limit',100),'F3上限',0,1e9))
    return dict(groups=p['groups'],unit=p['unit'],mode=p['mode'],shelters=p['rows'],hubs=p['hubs'],p1={'f1':ideal['value'],'allocation':ideal['x'].tolist()},p0={'f1':p0['f1'],'allocation':p0['allocation'],'certified':cert,'lower':lower,'etaLower':max(0,lower-ideal['value']),'etaUpper':max(0,p0['f1']-ideal['value'])},prime={'total':prime['total'],'upper':upper,'certified':prime['total']==upper,'allocation':prime['allocation']},cap=cap,delta=p['delta'],keep=p['keep'],front=front,recommended=rid,method=exact_note,fastCertified=bool(exact_fast and cert and (not p['keep'] or prime['total']==upper)),active=int(p['active'].sum()),mandatory=int(p['mandatory'].sum()),totalStock=sum(h['stock'] for h in p['hubs']),rho=RHO,rhoBoxEffect=float(RHO*min(p['w']/p['d'][p['active']])),rhoSumEffect=float(RHO*p['K']*p['w']),boxStep=float(min(p['w']/p['d'][p['active']])),round=p['h'],remainingRounds=p['R'],testedCandidates=len(valid))
