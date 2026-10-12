"""Share of the turn input that is tool results, and what a per-result cap would save.
Reads ~/.claude/projects/*/*.jsonl of the last 7 days; resets at each compaction (a context
never holds results from before one). Measured 2026-10-12, see debt turn-eviction-is-whole-context-summary-only."""
import json,os,glob,time,collections
root=os.path.expanduser('~/.claude/projects');cut=time.time()-7*86400
files=[f for f in glob.glob(root+'/*/*.jsonl') if os.path.getmtime(f)>cut]
CAPS=[6000,10000,20000,30000];tot_in=0;saved={c:0 for c in CAPS};saved_tool={c:collections.Counter() for c in CAPS};comp=0
allres=0;old=0;N=10
def norm(n):
    if n.startswith('mcp__'):
        p=n.split('__');return 'mcp:'+p[1]+'/'+p[-1]
    return n
def clen(c):
    if isinstance(c,str):return len(c)
    return sum(len(b.get('text','')) if b.get('type')=='text' else 2000 for b in (c or []) if isinstance(b,dict))
for f in files:
    names={};res=[];ctxnames=[]
    for line in open(f,encoding='utf-8',errors='replace'):
        try:d=json.loads(line)
        except:continue
        if d.get('isCompactSummary') or d.get('subtype')=='compact_boundary':
            res=[];comp+=1;continue
        m=d.get('message') or {};c=m.get('content')
        if d.get('type')=='assistant' and isinstance(c,list):
            u=m.get('usage') or {}
            tin=u.get('input_tokens',0)+u.get('cache_creation_input_tokens',0)+u.get('cache_read_input_tokens',0)
            if tin:
                tot_in+=tin
                allres+=sum(r[0] for r in res);old+=sum(r[0] for r in res[:max(0,len(res)-N)])
                for cap in CAPS:
                    for n,nm in res:
                        if n>cap:
                            saved[cap]+=n-cap;saved_tool[cap][nm]+=n-cap
            for b in c:
                if b.get('type')=='tool_use':names[b['id']]=norm(b['name'])
        elif d.get('type')=='user' and isinstance(c,list):
            for b in c:
                if b.get('type')=='tool_result':res.append((clen(b.get('content')),names.get(b.get('tool_use_id'),'?')))
print(f'input={tot_in/1e6:.0f}M compactions={comp}')
print(f'results share (compaction-aware): all={allres/3.5/tot_in:.1%} older_than_{N}={old/3.5/tot_in:.1%}')
for cap in CAPS:
    print(f'cap {cap}: saves ~{saved[cap]/3.5/1e6:.0f}M tok = {saved[cap]/3.5/tot_in:.2%} of input;',saved_tool[cap].most_common(4))
