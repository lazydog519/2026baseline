from collections import defaultdict
from heapq import heappop, heappush
from q1_optimized import compute_dag, topological_depth

class Model:
    def __init__(self, graph, bandwidth, same_wait, cross_wait):
        self.g,self.bw,self.same,self.cross=graph,bandwidth,same_wait,cross_wait
        self.ops,self.pred,self.succ=compute_dag(graph)
        self.order,self.depth=topological_depth(self.ops,self.pred,self.succ)
        self.prod,self.cons=defaultdict(set),defaultdict(set)
        self.allops={o['id']:o for o in graph['ops']}
        for e in graph['edges']:
            if e['source'] in self.allops:self.prod[e['target']].add(e['source'])
            if e['target'] in self.allops:self.cons[e['source']].add(e['target'])
        self.cp={}
        for o in self.order:
            self.cp[o]=self.ops[o]['cycles']+max((self.cp[x] for x in self.pred[o]),default=0)

    def describe(self, plan):
        mapping={int(o):s for o,s in plan['node_to_subgraph'].items()}
        tasks=sorted(set(mapping.values()));n=len(plan['core_schedules'])
        core={s:k for k,seq in enumerate(plan['core_schedules']) for s in seq}
        pred={s:set() for s in tasks};succ={s:set() for s in tasks}
        work={s:defaultdict(int) for s in tasks}
        for o,s in mapping.items():
            work[s][self.ops[o]['pipe']]+=self.ops[o]['cycles']
            for x in self.succ[o]:
                t=mapping[x]
                if s!=t:succ[s].add(t);pred[t].add(s)
        degree={s:len(pred[s]) for s in tasks}
        heap=[]
        for s in tasks:
            if degree[s]==0:heappush(heap,s)
        order=[]
        while heap:
            s=heappop(heap);order.append(s)
            for t in sorted(succ[s]):
                degree[t]-=1
                if degree[t]==0:heappush(heap,t)
        if len(order)!=len(tasks):raise ValueError('contracted Task graph has a cycle')
        io={s:[0,0] for s in tasks};inputs={s:set() for s in tasks};outputs={s:set() for s in tasks}
        for tensor in self.g['tensors']:
            tid,b=tensor['id'],tensor['size']
            producers={mapping[o] for o in self.prod[tid] if o in mapping}
            consumers={mapping[o] for o in self.cons[tid] if o in mapping}
            final=any(self.allops[o]['op']=='COPY_OUT' for o in self.cons[tid])
            for s in consumers-producers:io[s][0]+=b;inputs[s].add(tid)
            for s in producers:
                if final or not consumers or consumers-{s}:io[s][1]+=b;outputs[s].add(tid)
        duration={s:max(max(work[s].values(),default=0),sum(io[s])/self.bw) for s in tasks}
        byte_count=sum(sum(x) for x in io.values())
        bypipe=[defaultdict(int) for _ in range(n)]
        for s in tasks:
            for pipe,w in work[s].items():bypipe[core[s]][pipe]+=w
        bound=max(max(self.cp.values(),default=0),byte_count/self.bw,
                  max((w for row in bypipe for w in row.values()),default=0))
        return dict(tasks=tasks,core=core,pred=pred,succ=succ,order=order,
                    work=work,io=io,inputs=inputs,outputs=outputs,duration=duration,bytes=byte_count,bound=bound)

    def estimate(self, plan, view=None):
        v=view or self.describe(plan)
        pred={s:set(v['pred'][s]) for s in v['tasks']}
        seqprev={}
        for seq in plan['core_schedules']:
            for a,b in zip(seq,seq[1:]):pred[b].add(a);seqprev[b]=a
        succ={s:set() for s in v['tasks']}
        for s,ps in pred.items():
            for t in ps:succ[t].add(s)
        deg={s:len(ps) for s,ps in pred.items()};heap=[];finish={}
        for s,d in deg.items():
            if d==0:heappush(heap,s)
        while heap:
            s=heappop(heap)
            release=max((finish[t]+(self.cross if v['core'][t]!=v['core'][s] else
                         self.same if seqprev.get(s)==t else 0) for t in pred[s]),default=0)
            finish[s]=release+v['duration'][s]
            for t in sorted(succ[s]):
                deg[t]-=1
                if deg[t]==0:heappush(heap,t)
        if len(finish)!=len(v['tasks']):raise ValueError('combined dependency/core-order cycle')
        return max(max(finish.values(),default=0),v['bytes']/self.bw)

    def greedy(self, plan):
        v=self.describe(plan);n=len(plan['core_schedules']);rank={}
        for s in reversed(v['order']):
            rank[s]=v['duration'][s]+max((self.same+rank[t] for t in v['succ'][s]),default=0)
        degree={s:len(v['pred'][s]) for s in v['tasks']};heap=[]
        for s,d in degree.items():
            if not d:heappush(heap,(-rank[s],s))
        free=[0.]*n;sequences=[[] for _ in range(n)];placed={};finish={}
        while heap:
            _,s=heappop(heap)
            def eft(k):
                release=max([free[k]+self.same if sequences[k] else 0]+[
                    finish[t]+(self.cross if placed[t]!=k else 0) for t in v['pred'][s]])
                return release+v['duration'][s]
            k=min(range(n),key=lambda c:(eft(c),len(sequences[c]),c))
            free[k]=finish[s]=eft(k);placed[s]=k;sequences[k].append(s)
            for t in sorted(v['succ'][s]):
                degree[t]-=1
                if degree[t]==0:heappush(heap,(-rank[t],t))
        return {'node_to_subgraph':dict(plan['node_to_subgraph']),'core_schedules':sequences}

    def coarsen(self, plan, limit, trials):
        # Only neighbouring tasks in a global topological order are merged.
        # Contraction is revalidated; proxy improvements still require real evaluation.
        current=plan
        for _ in range(limit):
            v=self.describe(current);base=self.estimate(current,v);choices=[]
            adjacent={(a,b) for seq in current['core_schedules'] for a,b in zip(seq,seq[1:])}
            sizes={t['id']:t['size'] for t in self.g['tensors']}
            pairs=[(a,b) for a,b in zip(v['order'],v['order'][1:]) if (a,b) in adjacent]
            affinity=lambda a,b:sum(sizes[t] for t in (v['inputs'][a]|v['outputs'][a]) & v['inputs'][b])
            for a,b in sorted(pairs,key=lambda x:(-affinity(*x),x))[:trials]:
                candidate={'node_to_subgraph':{o:(a if s==b else s) for o,s in current['node_to_subgraph'].items()},
                           'core_schedules':[[s for s in seq if s!=b] for seq in current['core_schedules']]}
                score=self.estimate(candidate)
                if score<base-1e-9:choices.append((score,a,b,candidate))
            if not choices:break
            current=min(choices,key=lambda x:x[:3])[3]
        return current


