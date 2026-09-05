from pathlib import Path

p=Path('server.py')
s=p.read_text(encoding='utf-8')
s=s.replace('import base64, json, os, re, subprocess, tempfile, urllib.error, urllib.request', 'import base64, json, os, re, subprocess, tempfile, time, urllib.error, urllib.request', 1)
anchor='MAX_FILE = 12 * 1024 * 1024\n'
assert anchor in s
s=s.replace(anchor, anchor+'STATE_FILE = Path(os.environ.get("CHINESE_STUDY_STATE_FILE", "/var/lib/chinese-study/state.json"))\nMAX_STATE = 4 * 1024 * 1024\n', 1)
prompt='- grammar.options всегда 4 варианта, answer дословно равен одному из них.\n'
if prompt in s:
    s=s.replace(prompt, prompt+'- grammar.options должны быть попарно различными; только один вариант должен удовлетворять проверяемой конструкции.\n', 1)

cloud=r'''CLOUD_SYNC_JS = r"""(()=>{
const API='api/state';let rev=0,busy=false,pushTimer=null;
const arr=x=>Array.isArray(x)?x:[];
function stampDay(v){if(!v)return 0;const p=String(v).split('-').map(Number);return p.length===3?new Date(p[0],p[1]-1,p[2]).getTime():0}
function uniq(a,key,limit){const m=new Map();for(const x of arr(a)){const k=key(x);if(k!=null&&k!=='')m.set(String(k),x)}const z=[...m.values()];return limit?z.slice(-limit):z}
function mergeById(r,l,limit){return uniq([...arr(r),...arr(l)],x=>x?.id??x?.topicId??JSON.stringify(x),limit)}
function mergeHistory(r,l){return uniq([...arr(r),...arr(l)],x=>[x?.ts,x?.id??'',x?.source??'',x?.grade??'',x?.ok??''].join('|'),1400).sort((a,b)=>(a.ts||0)-(b.ts||0)).slice(-1400)}
function mergeWords(r,l){const out={...(r||{})};for(const [id,v] of Object.entries(l||{})){const a=out[id];if(!a){out[id]=v;continue}const al=Number(a.last||0),vl=Number(v?.last||0);if(vl>al)out[id]=v;else if(vl===al){const as=(a.seen||0)+(a.reps||0)+(a.lapses||0),vs=(v?.seen||0)+(v?.reps||0)+(v?.lapses||0);if(vs>as)out[id]=v}}return out}
function mergeSkills(r,l){const out={...(r||{})};for(const [k,v] of Object.entries(l||{})){const a=out[k]||{};out[k]=(Number(v?.total||0)>Number(a.total||0))?v:a}return out}
function mergeState(remote,local){remote=remote&&typeof remote==='object'?remote:{};local=local&&typeof local==='object'?local:{};const o={...remote,...local};o.words=mergeWords(remote.words,local.words);o.history=mergeHistory(remote.history,local.history);o.skills=mergeSkills(remote.skills,local.skills);o.materials=mergeById(remote.materials,local.materials,60);o.customWords=mergeById(remote.customWords,local.customWords);o.customTopics=mergeById(remote.customTopics,local.customTopics);o.recentTasks=uniq([...arr(remote.recentTasks),...arr(local.recentTasks)],x=>String(x),50);o.recentVocabModes=uniq([...arr(remote.recentVocabModes),...arr(local.recentVocabModes)],x=>String(x),24);o.sessions=Math.max(Number(remote.sessions||0),Number(local.sessions||0));o.streak=Math.max(Number(remote.streak||1),Number(local.streak||1));o.lastDay=stampDay(local.lastDay)>=stampDay(remote.lastDay)?local.lastDay:remote.lastDay;o.activeTopic=local.activeTopic||remote.activeTopic||null;return o}
function hydrate(){for(const w of arr(state.customWords)){if(typeof WORDS!=='undefined'&&!WORDS.some(x=>String(x.id)===String(w.id)))WORDS.push(w)}}
function apply(next){state=next;try{localStorage.setItem(KEY,JSON.stringify(state))}catch{}hydrate();try{renderAll()}catch{}}
async function post(){if(busy)return;busy=true;try{const r=await fetch(API,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_rev:rev,state}),cache:'no-store'});const d=await r.json().catch(()=>({}));if(r.status===409){rev=Number(d.rev||0);apply(mergeState(d.state||{},state));busy=false;return post()}if(r.ok)rev=Number(d.rev||rev)}catch{}finally{busy=false}}
function schedule(){clearTimeout(pushTimer);pushTimer=setTimeout(post,450)}
async function pull(first=false){try{const r=await fetch(API,{cache:'no-store'});if(!r.ok)return;const d=await r.json();const rr=Number(d.rev||0);if(!d.state){rev=rr;return post()}if(!first&&rr<=rev)return;const merged=mergeState(d.state,state);rev=rr;apply(merged);if(JSON.stringify(merged)!==JSON.stringify(d.state))schedule()}catch{}}
const originalSave=save;save=function(){originalSave();schedule()};
function boot(){pull(true);setInterval(()=>{pull(false);schedule()},15000);document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')schedule();else pull(false)});window.addEventListener('pagehide',()=>{try{fetch(API,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_rev:rev,state}),keepalive:true})}catch{}})}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();"""

def read_sync_state():
    try:
        obj=json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(obj,dict) and isinstance(obj.get("rev",0),int):return obj
    except Exception:pass
    return {"rev":0,"updated_at":0,"state":None}

def write_sync_state(value, current_rev):
    STATE_FILE.parent.mkdir(parents=True,exist_ok=True)
    payload={"rev":int(current_rev)+1,"updated_at":int(time.time()*1000),"state":value}
    tmp=STATE_FILE.with_name(STATE_FILE.name+".tmp")
    tmp.write_text(json.dumps(payload,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    os.replace(tmp,STATE_FILE)
    return payload

'''
marker='def http_json('
assert marker in s
s=s.replace(marker,cloud+marker,1)
get_marker='        if path=="/topic-study.js":\n'
assert get_marker in s
s=s.replace(get_marker,'        if path.rstrip("/")=="/api/state":\n            return self.send_json(200,read_sync_state())\n        if path=="/cloud-sync.js":\n            return self.send_bytes(200,CLOUD_SYNC_JS.encode("utf-8"),"application/javascript; charset=utf-8")\n'+get_marker,1)
old_post='    def do_POST(self):\n        if self.path.rstrip("/")!="/api/materials/analyze":return self.send_json(404,{"error":"not found"})\n'
assert old_post in s
new_post='''    def do_POST(self):
        path=self.path.split("?",1)[0].rstrip("/")
        if path=="/api/state":
            try:n=int(self.headers.get("Content-Length","0"))
            except:n=0
            if n<=0 or n>MAX_STATE:return self.send_json(413,{"error":"Слишком большой state."})
            try:body=json.loads(self.rfile.read(n).decode("utf-8"))
            except Exception:return self.send_json(400,{"error":"Некорректный JSON state."})
            incoming=body.get("state")
            if not isinstance(incoming,dict):return self.send_json(400,{"error":"state должен быть объектом."})
            current=read_sync_state();base=int(body.get("base_rev") or 0)
            if int(current.get("rev") or 0)!=base:return self.send_json(409,current)
            saved=write_sync_state(incoming,base)
            return self.send_json(200,{"ok":True,"rev":saved["rev"],"updated_at":saved["updated_at"]})
        if path!="/api/materials/analyze":return self.send_json(404,{"error":"not found"})
'''
s=s.replace(old_post,new_post,1)
s=s.replace('ChineseStudy/4.6','ChineseStudy/4.7').replace('Chinese Study 4.6','Chinese Study 4.7').replace('topic-study.js?v=4.6','topic-study.js?v=4.7')
html_old='html=html.replace("</body>",\'<script src="topic-study.js?v=4.7"></script>\\n</body>\')'
assert html_old in s
html_new='html=html.replace("</body>",\'<script src="topic-study.js?v=4.7"></script>\\n<script src="cloud-sync.js?v=4.7"></script>\\n</body>\')'
s=s.replace(html_old,html_new,1)
p.write_text(s,encoding='utf-8')

p=Path('ai-import.js');a=p.read_text(encoding='utf-8')
old="function variantGrammar(x){if(!x)return x;const opts=shuffle(x.opts||[]);return{...x,opts}}function variantReading"
assert old in a
new="function variantGrammar(x){if(!x)return x;const seen=new Set(),opts=[];for(const o of [x.a,...(x.opts||[])]){const v=String(o??'').trim();if(v&&!seen.has(v)){seen.add(v);opts.push(v)}}return{...x,opts:shuffle(opts)}}function variantReading"
a=a.replace(old,new,1)
marker="function rememberVocabMode(key)"
assert marker in a
wrapper="""const coreShowGrammar=showGrammar;showGrammar=function(s){const clean={...s,x:variantGrammar(s.x)};coreShowGrammar(clean);document.querySelectorAll('.optionbtn').forEach(btn=>{const fn=btn.onclick;if(typeof fn!=='function')return;btn.onclick=()=>{fn.call(btn);setTimeout(()=>{const next=document.getElementById('next');if(next){next.scrollIntoView({behavior:'smooth',block:'center'});try{next.focus({preventScroll:true})}catch{next.focus()}}},20)}})};
"""
a=a.replace(marker,wrapper+marker,1)
p.write_text(a,encoding='utf-8')

m=Path('manifest.txt').read_text(encoding='utf-8')
assert 'version=4.6' in m
Path('manifest.txt').write_text(m.replace('version=4.6','version=4.7'),encoding='utf-8')
