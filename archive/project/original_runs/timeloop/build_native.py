import concurrent.futures, json, os, pathlib, re, subprocess, time
ROOT = pathlib.Path(__file__).parent
REPO = ROOT / 'repo'
BIN = ROOT / 'msys64/ucrt64/bin'
BUILD = ROOT / 'build_native'
BUILD.mkdir(exist_ok=True)
os.environ['PATH'] = str(BIN) + os.pathsep + os.environ['PATH']
scon = (REPO / 'src/SConscript').read_text()
source_groups = {}
for name in ['common_sources', 'modellib_sources']:
    source_groups[name] = re.search(name + r'\s*=.*?Split\("""(.*?)"""\)', scon, re.S).group(1).split()
common = source_groups['common_sources'] + source_groups['modellib_sources']
# PAT is the unmodified power-area table supplied in this repository.
common = [s.replace('pat/pat.cpp', '../pat-public/src/pat/pat.cpp') for s in common]
include_args = ['-I' + str(REPO / 'src'), '-I' + str(REPO / 'pat-public/src'), '-I' + str(ROOT / 'msys64/ucrt64/include/ncursesw')]
flags = ['-O2', '-std=c++14', '-pthread', '-Wall', '-Wextra', '-DBUILD_BASE_DIR="' + REPO.as_posix() + '"']

def compile_one(source):
    src = REPO / 'src' / source
    obj = BUILD / (source.replace('../', '').replace('/', '_') + '.o')
    command = [str(BIN / 'g++.exe'), *flags, *include_args, '-c', str(src), '-o', str(obj)]
    if obj.exists() and obj.stat().st_mtime > src.stat().st_mtime:
        return obj
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    (BUILD / (obj.stem + '.log')).write_text(json.dumps(command) + '\n' + result.stdout + result.stderr, encoding='utf-8')
    print(source, result.returncode, flush=True)
    if result.returncode:
        print(result.stderr[-6000:], flush=True)
        raise RuntimeError(source)
    return obj

sources = common + ['applications/model/main.cpp']
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
    objects = dict(zip(sources, executor.map(compile_one, sources)))
for app in ['model']:
    objs = [str(objects[s]) for s in common]
    if app == 'mapper': objs.append(str(objects['mapspaces/mapspace-base.cpp']))
    objs.append(str(objects[f'applications/{app}/main.cpp']))
    command = [str(BIN / 'g++.exe'), '-pthread', *objs, '-L' + str(ROOT / 'msys64/ucrt64/lib'), '-lconfig++', '-lyaml-cpp', '-lncursesw', '-lboost_iostreams-mt', '-lboost_serialization-mt', '-o', str(BUILD / f'timeloop-{app}.exe')]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    (BUILD / f'link_{app}.log').write_text(json.dumps(command) + '\n' + result.stdout + result.stderr, encoding='utf-8')
    print('link', app, result.returncode, result.stderr[-6000:], flush=True)
    result.check_returncode()
