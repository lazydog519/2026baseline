"""A 题最小可复现基线：按原图中相连的计算操作分核。

本程序及代码在 OpenAI Codex（OpenAI，GPT-6）辅助下完成。模型版本发布日
当前无法核实；队员正式提交前应依比赛规定补录可核实的产品信息。
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path


def make_plan(graph, num_cores):
    """以非 COPY Op 的弱连通分量为单位，按计算周期贪心分配核心。"""
    if num_cores < 1:
        raise ValueError("num_cores must be positive")
    compute = {op["id"]: op for op in graph["ops"]
               if op["op"] not in ("COPY_IN", "COPY_OUT")}
    parent = {oid: oid for oid in compute}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[max(a, b)] = min(a, b)

    producer = defaultdict(list)
    consumer = defaultdict(list)
    for edge in graph["edges"]:
        a, b = edge["source"], edge["target"]
        if a in compute and b in compute:
            union(a, b)
        elif a in compute:
            producer[b].append(a)
        elif b in compute:
            consumer[a].append(b)
    for tid in producer.keys() & consumer.keys():
        for a in producer[tid]:
            for b in consumer[tid]:
                union(a, b)

    components = defaultdict(list)
    for oid in compute:
        components[find(oid)].append(oid)
    # 几种 Pipe 的周期不能直接相加为模拟 Makespan；这里只用于粗略分核。
    items = []
    for members in components.values():
        pipe_work = [0, 0]
        for oid in members:
            op = compute[oid]
            pipe_work[0 if op["pipe"] == "PIPE_M" else 1] += op["cycles"]
        items.append((max(pipe_work), min(members), members, pipe_work))
    items.sort(key=lambda item: (-item[0], item[1]))
    load = [[0, 0] for _ in range(num_cores)]
    assigned = [[] for _ in range(num_cores)]
    for _, _, members, work in items:
        core = min(range(num_cores), key=lambda c: (
            max(load[c][0] + work[0], load[c][1] + work[1]),
            sum(load[c]), c))
        assigned[core].extend(members)
        load[core][0] += work[0]
        load[core][1] += work[1]

    # 每核只建一个子图：场景 A 中只需一个 Task；场景 B 可以核内复用。
    mapping = {str(oid): core for core, members in enumerate(assigned)
               for oid in members}
    schedules = [[core] if members else []
                 for core, members in enumerate(assigned)]
    return {"node_to_subgraph": mapping, "core_schedules": schedules}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", type=Path)
    parser.add_argument("-n", "--num-cores", type=int, required=True)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    graph = json.loads(args.graph.read_text(encoding="utf-8"))
    plan = make_plan(graph, args.num_cores)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, separators=(",", ":")) + "\n",
                           encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
