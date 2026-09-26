"""Export already-frozen plans using the attachment's required filenames."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parent
index=[]
with zipfile.ZipFile(ROOT/'final/plans_q3.zip','w',zipfile.ZIP_DEFLATED) as archive:
    for run in ('full1to4_v2','full5_v2'):
        manifest=json.loads((ROOT/run/'generation_manifest.json').read_text(encoding='utf-8'))
        for job in manifest['jobs']:
            case,n=job['case'],job['cores']
            path=ROOT/run/'plans'/f'{case}_n{n}.json'
            assert hashlib.sha256(path.read_bytes()).hexdigest()==job['plan_sha256']
            name=f'n{n}/{case}_multicore_res.json'
            archive.write(path,name)
            index.append(dict(case=case,cores=n,member=name,sha256=job['plan_sha256']))
assert len(index)==500 and len({r['member'] for r in index})==500
(ROOT/'final/plan_index.json').write_text(json.dumps(index,indent=2)+'\n',encoding='utf-8')
print('Exported 500 frozen plans; no optimization or evaluation performed.')
