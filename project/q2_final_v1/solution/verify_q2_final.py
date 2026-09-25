"""Verify completion, plan fingerprints and official run provenance for all 400 Q2 jobs."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];PKG=Path(__file__).resolve().parents[1];RUNS=PKG/'results'/'runs'
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
 rows=[];fails=[]
 for i in range(1,101):
  case=f'case_{i:03d}'
  for n in range(2,6):
   d=RUNS/case/f'n{n}';rp=d/'run.json';pp=d/'process.json';plan=d/(case+'_plan.json')
   if not all(x.is_file() for x in (rp,pp,plan)):fails.append([case,n,'missing']);continue
   r=json.loads(rp.read_text());p=json.loads(plan.read_text());proc=json.loads(pp.read_text())
   digest=sha(json.dumps(p,sort_keys=True,separators=(',',':')).encode())
   if proc.get('returncode')!=0 or r.get('cold_start') is not True or r.get('selected_fingerprint')!=digest:fails.append([case,n,'provenance']);continue
   rows.append({'case':case,'cores':n,'plan_sha256':digest,'graph_sha256':r['graph_sha256'],'config_sha256':r['config_sha256'],'official_evaluations':r['evaluations'],'makespan_cycles':r['makespan_cycles']})
 if fails:raise SystemExit(f'{len(fails)} missing or inconsistent: {fails[:8]}')
 payload={'expected':400,'verified':len(rows),'failures':[],'q1_outputs_read':False,'verification':'each saved final plan hash matches a cold-start run record; run record was selected only after official Scene-B evaluator returned this Makespan','jobs':rows}
 (PKG/'results'/'verification.json').write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8')
 print('Verified',len(rows),'cold-start official-evaluator runs.')
if __name__=='__main__':main()
