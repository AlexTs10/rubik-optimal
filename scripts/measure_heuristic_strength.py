import sys, random, statistics
sys.path.insert(0, "src")
from rubik_optimal.cube import CubeState
from rubik_optimal.moves import ALL_MOVES, same_face
from rubik_optimal.search.bfs import exact_distance_bfs
from rubik_optimal.search.heuristics import (
    combined_table_lower_bound, additive_edge_cpdb_lower_bound,
    corner_pattern_database_lower_bound, edge_pattern_database_lower_bound)

def inverse(c):
    cp=[0]*8; co=[0]*8; ep=[0]*12; eo=[0]*12
    for i in range(8):
        cp[c.cp[i]]=i; co[c.cp[i]]=(-c.co[i])%3
    for i in range(12):
        ep[c.ep[i]]=i; eo[c.ep[i]]=c.eo[i]%2
    return CubeState(tuple(cp),tuple(co),tuple(ep),tuple(eo))
def h_cur(c): return combined_table_lower_bound(c)
def h_imp(c): return max(combined_table_lower_bound(c), additive_edge_cpdb_lower_bound(c))
def h_dual(c): return max(h_imp(c), h_imp(inverse(c)))

rng=random.Random(2026)
def scr(k):
    s=[];p=None
    while len(s)<k:
        m=rng.choice(ALL_MOVES)
        if same_face(p,m): continue
        s.append(m);p=m
    return s

print("=== STRENGTH (no BFS): higher h = exponentially less search ===", flush=True)
print(f"{'state':13}{'corner':>7}{'edgeMax':>8}{'cpdbSum':>8}{'current':>8}{'improved':>9}{'+dual':>7}", flush=True)
def row(lbl,c):
    cur,imp,dual=h_cur(c),h_imp(c),h_dual(c)
    print(f"{lbl:13}{corner_pattern_database_lower_bound(c):7d}{edge_pattern_database_lower_bound(c):8d}"
          f"{additive_edge_cpdb_lower_bound(c):8d}{cur:8d}{imp:9d}{dual:7d}",flush=True)
    return cur,dual
deltas=[]
for k in [10,12,14,16,18,20]:
    cur,dual=row(f"rand_d{k}", CubeState.from_sequence(scr(k))); deltas.append(dual-cur)
sf=CubeState(cp=tuple(range(8)),co=(0,)*8,ep=tuple(range(12)),eo=(1,)*12)
cur,dual=row("superflip20", sf)
print(f"\n  superflip: current h={cur} -> improved+dual h={dual} (+{dual-cur}); node factor ~13.3^{dual-cur}={13.3**(dual-cur):.2e}",flush=True)
print(f"  mean h-gain on random deep states: +{statistics.mean(deltas):.2f}",flush=True)
print("\n=== quick admissibility (BFS depth<=4) ===",flush=True)
bad=invb=n=0
for k in range(1,5):
    for _ in range(4):
        c=CubeState.from_sequence(scr(k)); d,_=exact_distance_bfs(c,max_depth=4)
        if d is None: continue
        n+=1
        di,_=exact_distance_bfs(inverse(c),max_depth=4)
        if di!=d: invb+=1
        if h_dual(c)>d: bad+=1; print(f"  INADMISSIBLE dual h={h_dual(c)}>d={d}",flush=True)
print(f"  checked {n}: inadmissible={bad}, inverse_mismatch={invb}",flush=True)
print("ALL_DONE",flush=True)
