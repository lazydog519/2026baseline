"""FIFO on an exogenous request trace in O(events log requests) time.

For pool p, virtual service V_p(t)=integral B_p / active_p(t) dt. A request
finishes when V_p reaches its issue-time V_p plus its byte size. A min-heap
therefore replaces per-event scanning of every active transfer.
"""
from collections import deque
import heapq
import math


def fifo_trace(requests, capacity, ddr_bw, l2_bw):
    future = sorted((float(t), i, key, size, read)
                    for i, (t, key, size, read) in enumerate(requests))
    index, now, used = 0, 0., 0
    hit_bytes = read_bytes = ddr_bytes = 0
    insertions = evictions = hits = 0
    entries, queue = {}, deque()
    pools = [[], []]
    virtual = [0., 0.]
    bandwidth = (ddr_bw, l2_bw)
    while index < len(future) or pools[0] or pools[1]:
        before_index = index
        before_active = len(pools[0])+len(pools[1])
        next_issue = future[index][0] if index < len(future) else float('inf')
        next_end = [now + max(0., pool[0][0]-virtual[p])*len(pool)/bandwidth[p]
                    if pool else float('inf') for p, pool in enumerate(pools)]
        nxt = min(next_issue, *next_end)
        for p, pool in enumerate(pools):
            if pool:
                virtual[p] += (nxt-now)*bandwidth[p]/len(pool)
                # A computed completion can round a few bytes below its
                # threshold after a long run; preserve the event ordering.
                if next_end[p] <= nxt+4*math.ulp(nxt):
                    virtual[p] = max(virtual[p], pool[0][0])
        now = nxt
        completed = []
        for p, pool in enumerate(pools):
            while pool and pool[0][0] <= virtual[p]+1e-7:
                _, i, key, size, read = heapq.heappop(pool)
                completed.append((i, p, key, size, read))
        for i, p, key, size, read in sorted(completed):
            if p == 0 and read and key not in entries and size <= capacity:
                while queue and used+size > capacity:
                    used -= entries.pop(queue.popleft())
                    evictions += 1
                entries[key] = size
                queue.append(key)
                used += size
                insertions += 1
        while index < len(future) and future[index][0] <= now+1e-9:
            _, i, key, size, read = future[index]
            hit = read and key in entries
            if read:
                read_bytes += size
            if hit:
                hit_bytes += size
                hits += 1
            else:
                ddr_bytes += size
            if size:
                p = int(hit)
                heapq.heappush(pools[p], (virtual[p]+float(size), i, key, size, read))
            index += 1
        if index == before_index and len(pools[0])+len(pools[1]) == before_active:
            raise RuntimeError(f'FIFO virtual-time nonprogress at {now}: '
                               f'next issue {next_issue}, next ends {next_end}, '
                               f'active {before_active}, consumed {index}/{len(future)}, '
                               f'virtual {virtual}, '
                               f'thresholds {[pool[0][0] if pool else None for pool in pools]}, '
                               f'ulp {math.ulp(now)}')
    return dict(hit_bytes=hit_bytes, read_bytes=read_bytes, ddr_bytes=ddr_bytes,
                hits=hits, insertions=insertions, evictions=evictions, trace_end=now)
