"""Record exact input/evaluator preservation against the previously saved official bundle."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project',type=Path,required=True)
    ap.add_argument('--reference',type=Path,required=True)
    a=ap.parse_args()
    source=a.project.resolve()/'official'
    reference=a.reference.resolve()/'project/official'
    files=[p for p in source.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
    mismatch=[]
    for p in files:
        other=reference/p.relative_to(source)
        if not other.is_file() or sha(p)!=sha(other):
            mismatch.append(str(p.relative_to(source)))
    report=dict(official_files=len(files),unchanged=len(files)-len(mismatch),mismatches=mismatch,
                config_sha256=sha(source/'data/config.txt'))
    (Path(__file__).resolve().parent/'official_integrity.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    if len(files)!=114 or mismatch:
        raise SystemExit(1)


if __name__=='__main__':main()
