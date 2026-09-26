"""Cold Q1 reproduction runner. Reads only official input graphs and this package's solver/config."""
import argparse, concurrent.futures, subprocess, sys, time, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
PKG=Path(__file__).resolve().parents[1]
def job(case,n,out):
    d=out/case/f"n{n}"; d.mkdir(parents=True,exist_ok=True)
    graph=ROOT/"project"/"official"/"data"/(case+".json")
    cmd=[sys.executable,"-X","utf8",str(PKG/"solution"/"q1_cold.py"),str(graph),"-n",str(n),"--official-code",str(ROOT/"project"/"official"/"code"),"--config",str(ROOT/"project"/"official"/"data"/"config.txt"),"--search-config",str(PKG/"solution"/"q1_cold_config.json"),"-o",str(d/(case+"_plan.json")),"--trace-dir",str(d)]
    t=time.perf_counter()
    with (d/"console.log").open("w",encoding="utf-8") as log: rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
    row={"case":case,"cores":n,"returncode":rc,"process_wall_s":time.perf_counter()-t}
    if rc==0: row.update(json.loads((d/"run.json").read_text(encoding="utf-8")))
    (d/"process.json").write_text(json.dumps(row,indent=2)+"\n")
    return row
def main():
    p=argparse.ArgumentParser();p.add_argument("--workers",type=int,default=2);p.add_argument("--cases",type=int,nargs="+",default=list(range(1,101)));p.add_argument("--cores",type=int,nargs="+",default=[2,3,4,5]);p.add_argument("--output",type=Path,default=PKG/"results"/"reproduction");a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
      futures=[pool.submit(job,f"case_{i:03d}",n,out) for i in a.cases for n in a.cores]
      failures=[]
      for f in concurrent.futures.as_completed(futures):
        r=f.result(); print(r["case"],r["cores"],r["returncode"],round(r["process_wall_s"],2),flush=True)
        if r["returncode"]: failures.append(r)
    if failures: raise SystemExit(f"failed jobs: {failures}")
if __name__=="__main__": main()
