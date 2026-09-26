import concurrent.futures, json, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
PKG=Path(__file__).resolve().parents[1]
OUT=PKG/"results"/"runs"
CFG=PKG/"solution"/"q2_final_config.json"
def job(item):
    case,n=item; name=f"case_{case:03d}"; d=OUT/name/f"n{n}"; d.mkdir(parents=True,exist_ok=True)
    old=d/"process.json"
    if old.exists() and (d/"run.json").exists():
        try:
            saved=json.loads(old.read_text())
            if saved.get("returncode")==0: return saved
        except Exception: pass
    graph=ROOT/"project"/"official"/"data"/(name+".json")
    cmd=[sys.executable,"-X","utf8",str(PKG/"solution"/"q2_final_solver.py"),str(graph),"-n",str(n),"--official-code",str(ROOT/"project"/"official"/"code"),"--config",str(ROOT/"project"/"official"/"data"/"config.txt"),"--search-config",str(CFG),"--trace-dir",str(d),"-o",str(d/(name+"_plan.json"))]
    t=time.perf_counter()
    with (d/"console.log").open("w",encoding="utf-8") as log: rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
    row={"case":name,"cores":n,"returncode":rc,"process_wall_s":time.perf_counter()-t}
    if rc==0: row.update(json.loads((d/"run.json").read_text()))
    (d/"process.json").write_text(json.dumps(row,indent=2)+"\n")
    if rc==0 and not (case==44 and n==5):
        (d/"official_result.json.gz").unlink(missing_ok=True)
    return row
def main():
    jobs=[(i,n) for i in range(1,101) for n in range(2,6)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        for f in concurrent.futures.as_completed([ex.submit(job,x) for x in jobs]):
            r=f.result(); print(r["case"],r["cores"],r["returncode"],r.get("makespan_cycles"),round(r["process_wall_s"],2),flush=True)
            if r["returncode"]: print("FAILED",r["case"],r["cores"],flush=True)
if __name__=="__main__": main()
