import json, hashlib
from pathlib import Path
from statistics import mean
from collections import Counter
root=Path.cwd(); out=root/'results/analysis/recovery_v3_20261013'; old=root/'results/analysis/recovery_v2_20261013'
def read(base,name): return json.loads((base/name).read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def key(r): return (r['case'],r['planner'],r['seed'])
rows=read(out,'episodes.json'); historical={key(r):r for r in read(old,'episodes.json') if r['mode']=='recovery_v2' and r['planner']=='hybrid_astar'}
traces=read(out,'trajectories.json'); ht={key(r):r for r in read(old,'trajectories.json') if r['mode']=='recovery_v2' and r['planner']=='hybrid_astar'}
m=read(out,'manifest.json'); hm=read(old,'manifest.json')
result={'episodes':len(rows),'v2_historical_pairs':len(historical),'v2_result_differences':[], 'v2_sample_differences':[], 'config_equal':{k:m[k]==hm[k] for k in ('cases','seeds','vehicle','tracker','simulation','noise','obstacle_guard','planning_timeout_s')},'artifact_hash_mismatches':[], 'input_hash_mismatches':[], 'source_hash_mismatches':[]}
result['config_equal']['paths_content']=read(out,'paths.json')==read(old,'paths.json')
for r in rows:
 if r['mode']=='recovery_v2':
  for k,v in historical[key(r)].items():
   if k not in ('replanning_time_s','replan_validation_time_s') and r.get(k)!=v: result['v2_result_differences'].append([key(r),k,v,r.get(k)])
for t in traces:
 if t['mode']=='recovery_v2' and t['samples']!=ht[key(t)]['samples']: result['v2_sample_differences'].append(key(t))
for name,hashes in [('artifact',read(out,'complete.json')['artifacts']),('input',m['inputs']),('source',m['source_sha256'])]:
 for p,h in hashes.items():
  path=(out/p if name=='artifact' else Path(p) if name=='input' else root/p)
  if sha(path)!=h: result[name+'_hash_mismatches'].append(p)
a={key(r):r for r in rows if r['mode']=='recovery_v2'}; b={key(r):r for r in rows if r['mode']=='recovery_v3'}
same=[k for k in a if a[k]['position_success'] and b[k]['position_success']]
result['paired_success']={'n':len(same),'v2_mean_s':mean(a[k]['time_s'] for k in same),'v3_mean_s':mean(b[k]['time_s'] for k in same)}
result['rescued']=[k for k in a if not a[k]['position_success'] and b[k]['position_success']]
result['regressed']=[k for k in a if a[k]['position_success'] and not b[k]['position_success']]
result['accepted_episodes']=[r for r in b.values() if r['alternative_accepted_count']]
result['v3_candidates_by_reason']=dict(Counter(e['reason'].split(':',1)[-1] for t in traces if t['mode']=='recovery_v3' for e in t['recovery_events'] if e['kind']=='alternative'))
result['v3_preview_outcomes']=dict(Counter(e['reason'] for t in traces if t['mode']=='recovery_v3' for e in t['recovery_events'] if e['kind'] in ('alternative_accepted','alternative_rejected')))
result['v3_case_summary']=[{'case':case, 'statuses':dict(Counter(r['status'] for r in b.values() if r['case']==case)), 'candidates':sum(r['alternative_count'] for r in b.values() if r['case']==case),'accepted':sum(r['alternative_accepted_count'] for r in b.values() if r['case']==case),'planning_s':sum(r['replanning_time_s'] for r in b.values() if r['case']==case)} for case in dict.fromkeys(r['case'] for r in rows)]
result['timing']={mode:{k:sum(r[k] for r in rows if r['mode']==mode) for k in ('replanning_time_s','replan_validation_time_s','alternative_planning_time_s','alternative_expanded_nodes')} for mode in ('recovery_v2','recovery_v3')}
result['maximum_candidate_expanded_nodes']=max(e['expanded_nodes'] for t in traces if t['mode']=='recovery_v3' for e in t['recovery_events'] if e['kind']=='alternative')
(out/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
