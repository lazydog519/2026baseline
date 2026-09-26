"""Graph-local resource model. This is not the official execution scheduler.

It retains compute dependencies, four serial pipes, shared fair-service pools
and completion-time FIFO insertion. It approximates the local instruction order
and treats sequential live-range spills separately from the event graph.
"""
from collections import defaultdict, OrderedDict
import heapq
import math

from graph_model import Problem
from q1_optimized import topological_depth


class InputGraph(Problem):
    def __init__(self, graph, cores, cfg):
        super().__init__(graph, cores, cfg['bandwidth']['bandwidth'],
                         cfg['multicore_scene_b']['cross_core_copy_delay_cycles'],
                         cfg['capacity'])
        self.cfg = cfg
        self.cache = cfg['problem_3']['cache_capacity_bytes']
        self.cache_bw = cfg['problem_3']['cache_bandwidth_bytes_per_cycle']
        unseen, self.components = set(self.ops), []
        while unseen:
            start = min(unseen)
            unseen.remove(start)
            group, todo = [start], [start]
            while todo:
                op = todo.pop()
                neighbors = (self.pred[op] | self.succ[op]) & unseen
                unseen.difference_update(neighbors)
                todo.extend(sorted(neighbors))
                group.extend(sorted(neighbors))
            self.components.append(group)
        self.inputs_by_op = defaultdict(set)
        for tid, ps, cs, _ in self.tensor_views:
            if not ps:
                for op in cs:
                    self.inputs_by_op[op].add(tid)
        work = sum(op['cycles'] for op in self.ops.values())
        depth = max(self.depth.values(), default=1)
        # Both terms are graph-derived operation-depth scales.
        self.width = max(self.width, math.ceil(cores*self.delay*depth/max(1, work)))
        self.width = min(depth, max(2, self.width))
        self.profile = dict(ops=len(self.ops), tensors=len(self.tensors),
                            components=len(self.components), depth=depth,
                            compute_cycles=work, band_depth=self.width,
                            largest_component_fraction=max(map(len, self.components), default=0)
                            / max(1, len(self.ops)))

    def validate(self, plan):
        if set(plan) != {'node_to_subgraph', 'core_schedules'}:
            raise ValueError('unexpected output fields')
        if len(plan['core_schedules']) != self.n:
            raise ValueError('core count')
        m, _, groups = self.view(plan)
        if set(m) != set(self.ops) or len(m) != len(plan['node_to_subgraph']):
            raise ValueError('operation coverage')
        seq = [s for row in plan['core_schedules'] for s in row]
        if len(seq) != len(set(seq)) or set(seq) != set(groups):
            raise ValueError('subgraph coverage')
        if any(type(s) is not int or s < 0 for s in seq):
            raise ValueError('nonnegative integer sgid required')
        pred, succ = {s:set() for s in seq}, {s:set() for s in seq}
        for u in self.order:
            for v in self.succ[u]:
                if m[u] != m[v]:
                    pred[m[v]].add(m[u]); succ[m[u]].add(m[v])
        for row in plan['core_schedules']:
            for u, v in zip(row, row[1:]):
                pred[v].add(u); succ[u].add(v)
        topological_depth(set(seq), pred, succ)

    def component_plan(self, affinity=False):
        load = [[0., 0.] for _ in range(self.n)]
        resident_inputs = [set() for _ in range(self.n)]
        mapping, schedules = {}, [[] for _ in range(self.n)]
        items = []
        for group in self.components:
            work = [sum(self.ops[o]['cycles'] for o in group if self.ops[o]['pipe']==p)
                    for p in ('PIPE_M', 'PIPE_V')]
            reads = set().union(*(self.inputs_by_op[o] for o in group))
            items.append((max(work), min(group), group, work, reads))
        for sg, (_, _, group, work, reads) in enumerate(sorted(items, key=lambda x:(-x[0],x[1]))):
            def cost(c):
                new_io = sum(self.tensors[t]['size'] for t in reads-resident_inputs[c])
                return (max(load[c][j]+work[j] for j in (0,1)) +
                        (new_io/self.bw if affinity else 0), sum(load[c]), c)
            core = min(range(self.n), key=cost)
            schedules[core].append(sg)
            resident_inputs[core].update(reads)
            for j in (0,1):
                load[core][j] += work[j]
            mapping.update({str(o):sg for o in group})
        return dict(node_to_subgraph=mapping, core_schedules=schedules)

    def order_view(self, plan):
        mapping, assignment, _ = self.view(plan)
        groups = defaultdict(list)
        for op in self.order:
            groups[mapping[op]].append(op)
        seqs = [[o for s in row for o in groups[s]] for row in plan['core_schedules']]
        positions = {op:i for row in seqs for i,op in enumerate(row)}
        core = {op:assignment[sg] for op,sg in mapping.items()}
        return core, positions, seqs

    def spill_bytes(self, plan):
        """Sequential next-use estimate, not a capacity feasibility certificate."""
        core, _, seqs = self.order_view(plan)
        related, prod = defaultdict(set), defaultdict(set)
        backing = set()
        for tid, ps, cs, output in self.tensor_views:
            for o in ps+cs:
                related[o].add(tid)
            for o in ps:
                prod[o].add(tid)
            if not ps or output or not cs or any(core[p]!=core[c] for p in ps for c in cs):
                backing.add(tid)
        total, peak_excess = 0, 0
        for row in seqs:
            uses = defaultdict(list)
            for i,o in enumerate(row):
                for t in related[o]:
                    uses[t].append(i)
            cursor = dict.fromkeys(uses, 0)
            resident = {'L1':set(), 'UB':set()}
            used = dict.fromkeys(resident, 0)
            seen, stored = set(), set(backing)
            for i,o in enumerate(row):
                protected = related[o]
                for t in sorted(protected):
                    place = self.tensors[t]['pos']
                    place = 'UB' if place=='DDR' else place
                    if place not in resident:
                        continue
                    if t in resident[place]:
                        continue
                    size = self.tensors[t]['size']
                    peak_excess = max(peak_excess, used[place]+size-self.capacity[place])
                    while used[place]+size > self.capacity[place]:
                        candidates = resident[place]-protected
                        if not candidates:
                            # The surrogate order may differ from official Step 1–2.
                            return total + 2*max(0, used[place]+size-self.capacity[place]), peak_excess
                        victim = max(candidates, key=lambda x:(uses[x][cursor[x]]
                                   if cursor[x]<len(uses[x]) else math.inf, self.tensors[x]['size'], x))
                        if cursor[victim]<len(uses[victim]) and victim not in stored:
                            total += self.tensors[victim]['size']
                            stored.add(victim)
                        resident[place].remove(victim)
                        used[place] -= self.tensors[victim]['size']
                    if t in seen and t not in prod[o]:
                        total += size
                    resident[place].add(t); used[place] += size; seen.add(t)
                for t in protected:
                    cursor[t] += 1
                    if cursor[t] == len(uses[t]):
                        place = self.tensors[t]['pos']
                        place = 'UB' if place=='DDR' else place
                        if place in resident and t in resident[place]:
                            resident[place].remove(t)
                            used[place] -= self.tensors[t]['size']
        return total, peak_excess

    def event_graph(self, plan):
        core, pos, _ = self.order_view(plan)
        nodes, parents, ranks = [], [], []
        def node(c, pipe, work, key=None, read=False, rank=0):
            idx = len(nodes)
            nodes.append((c, pipe, float(work), key, read))
            parents.append({})
            ranks.append(rank)
            return idx
        def edge(u,v,delay=0):
            parents[v][u] = max(delay, parents[v].get(u,0))
        op_node = {o:node(core[o],self.ops[o]['pipe'],self.ops[o]['cycles'],rank=3*pos[o]+1)
                   for o in self.order}
        for u in self.order:
            for v in self.succ[u]:
                edge(op_node[u],op_node[v])
        def read(c,tid,size,consumers,source=None):
            r = node(c,'PIPE_MTE2',size,tid,True,3*min(pos[o] for o in consumers))
            if source is not None:
                edge(source,r,self.delay)
            for o in consumers:
                edge(r,op_node[o])
            return r
        def write(c,tid,size,producers):
            w = node(c,'PIPE_MTE3',size,tid,False,3*max(pos[o] for o in producers)+2)
            for o in producers:
                edge(op_node[o],w)
            return w
        for tid, ps, cs, output in self.tensor_views:
            size = self.tensors[tid]['size']
            sources, targets = defaultdict(list), defaultdict(list)
            for o in ps: sources[core[o]].append(o)
            for o in cs: targets[core[o]].append(o)
            if not ps:
                for c,consumers in targets.items():
                    read(c,tid,size,consumers)
            if ps and (output or not cs):
                for c,producers in sources.items():
                    write(c,tid,size,producers)
            for a,producers in sources.items():
                for b,consumers in targets.items():
                    if a!=b:
                        read(b,tid,size,consumers,write(a,tid,size,producers))
        for u,v,size in self.direct_edges:
            if core[u]!=core[v]:
                read(core[v],('edge',u,v),size,[v],write(core[u],('edge',u,v),size,[u]))
        pipes = defaultdict(list)
        for i,(c,p,_,_,_) in enumerate(nodes):
            pipes[c,p].append(i)
        for values in pipes.values():
            ordered = sorted(values,key=lambda i:(ranks[i],i))
            for u,v in zip(ordered,ordered[1:]):
                edge(u,v)
        return nodes, parents

    def describe(self, plan):
        self.validate(plan)
        nodes, parents = self.event_graph(plan)
        stats = simulate(nodes, parents, self.cache, self.bw, self.cache_bw)
        spill, excess = self.spill_bytes(plan)
        stats.update(spill_bytes=spill, sequential_excess_bytes=max(0,excess),
                     spill_cycles=spill/self.bw,
                     projected_copy_bytes=stats['ddr_bytes']+stats['hit_bytes']+spill)
        return stats


def simulate(nodes, parents, capacity, ddr_bw, l2_bw):
    """FIFO and fair sharing on our coarse node DAG; no local spill expansion."""
    succ = [[] for _ in nodes]
    indeg, release = [], [0.]*len(nodes)
    for v,ps in enumerate(parents):
        indeg.append(len(ps))
        for u,delay in ps.items():
            succ[u].append((v,delay))
    ready = [(0.,i) for i,d in enumerate(indeg) if d==0]
    heapq.heapify(ready)
    compute, pools = [], [{},{}]
    entries, used = OrderedDict(), 0
    now, done, hits, reads, ddr, evictions = 0.,0,0,0,0,0
    while done < len(nodes):
        while ready and ready[0][0] <= now+1e-9:
            _,i = heapq.heappop(ready)
            _,p,work,key,read = nodes[i]
            if p in ('PIPE_MTE2','PIPE_MTE3') and work>0:
                hit = read and key in entries
                if read: reads += work
                if hit: hits += work
                else: ddr += work
                pools[int(hit)][i] = work
            else:
                heapq.heappush(compute,(now+max(1.,work),i))
        targets = [min(pool.values())*len(pool)/bw if pool else math.inf
                   for pool,bw in zip(pools,(ddr_bw,l2_bw))]
        nxt = min(ready[0][0] if ready else math.inf,
                  compute[0][0] if compute else math.inf, now+min(targets))
        if not math.isfinite(nxt):
            raise ValueError('coarse pipe-order model has a dependency cycle')
        dt = max(0.,nxt-now)
        completed = []
        for p,(pool,bw) in enumerate(zip(pools,(ddr_bw,l2_bw))):
            if pool:
                service = dt*bw/len(pool)
                if abs(dt-targets[p]) <= 4*math.ulp(max(1.,nxt)):
                    service = max(service,min(pool.values()))
                for i in list(pool):
                    pool[i] -= service
                    if pool[i] <= 1e-7:
                        completed.append(i); del pool[i]
        now = nxt
        while compute and compute[0][0] <= now+1e-9:
            completed.append(heapq.heappop(compute)[1])
        for i in sorted(completed):
            _,_,size,key,read = nodes[i]
            # The attachment attempts insertion at EVERY COPY_IN completion.
            # An existing entry is unchanged; an evicted in-flight hit can reinsert.
            if read and size>0 and size<=capacity and key not in entries:
                while entries and used+size>capacity:
                    _,old = entries.popitem(last=False)
                    used -= old; evictions += 1
                entries[key] = size; used += size
            done += 1
            for v,delay in succ[i]:
                release[v] = max(release[v],now+delay)
                indeg[v] -= 1
                if indeg[v]==0:
                    heapq.heappush(ready,(release[v],v))
    return dict(event_cycles=now,ddr_bytes=ddr,hit_bytes=hits,read_bytes=reads,
                estimated_hit_rate=hits/reads if reads else 0.,evictions=evictions)
