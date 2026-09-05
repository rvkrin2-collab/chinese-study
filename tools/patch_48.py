from pathlib import Path
import re

p=Path('server.py')
s=p.read_text(encoding='utf-8')

# Persistent canonical library, separate from progress state.
anchor='STATE_FILE = Path(os.environ.get("CHINESE_STUDY_STATE_FILE", "/var/lib/chinese-study/state.json"))\nMAX_STATE = 4 * 1024 * 1024\n'
assert anchor in s
s=s.replace(anchor, anchor+'LIBRARY_FILE = Path(os.environ.get("CHINESE_STUDY_LIBRARY_FILE", "/var/lib/chinese-study/library.json"))\n', 1)

cloud=r'''CLOUD_SYNC_JS = r"""(()=>{
const STATE_API='api/state', LIB_API='api/library';
let rev=0,busy=false,dirty=false,pushTimer=null,libTimer=null;
const arr=x=>Array.isArray(x)?x:[];
const stable=x=>JSON.stringify(x??null);
function stampDay(v){if(!v)return 0;const p=String(v).split('-').map(Number);return p.length===3?new Date(p[0],p[1]-1,p[2]).getTime():0}
function uniq(a,key,limit){const m=new Map();for(const x of arr(a)){const k=key(x);if(k!=null&&k!=='')m.set(String(k),x)}const z=[...m.values()];return limit?z.slice(-limit):z}
function mergeById(r,l,limit){return uniq([...arr(r),...arr(l)],x=>x?.id??x?.topicId??JSON.stringify(x),limit)}
function mergeHistory(r,l){return uniq([...arr(r),...arr(l)],x=>[x?.ts,x?.id??'',x?.source??'',x?.grade??'',x?.ok??''].join('|'),1400).sort((a,b)=>(a.ts||0)-(b.ts||0)).slice(-1400)}
function mergeWords(r,l){const out={...(r||{})};for(const [id,v] of Object.entries(l||{})){const a=out[id];if(!a){out[id]=v;continue}const al=Number(a.last||0),vl=Number(v?.last||0);if(vl>al)out[id]=v;else if(vl===al){const as=(a.seen||0)+(a.reps||0)+(a.lapses||0),vs=(v?.seen||0)+(v?.reps||0)+(v?.lapses||0);if(vs>as)out[id]=v}}return out}
function mergeSkills(r,l){const out={...(r||{})};for(const [k,v] of Object.entries(l||{})){const a=out[k]||{};out[k]=(Number(v?.total||0)>Number(a.total||0))?v:a}return out}
function newerTopic(a,b){if(!a)return b;if(!b)return a;return Number(b.started||0)>Number(a.started||0)?b:a}
function mergeState(remote,local){remote=remote&&typeof remote==='object'?remote:{};local=local&&typeof local==='object'?local:{};const o={...remote,...local};o.words=mergeWords(remote.words,local.words);o.history=mergeHistory(remote.history,local.history);o.skills=mergeSkills(remote.skills,local.skills);o.materials=mergeById(remote.materials,local.materials,80);o.customWords=mergeById(remote.customWords,local.customWords);o.customTopics=mergeById(remote.customTopics,local.customTopics);o.recentTasks=uniq([...arr(remote.recentTasks),...arr(local.recentTasks)],x=>String(x),50);o.recentVocabModes=uniq([...arr(remote.recentVocabModes),...arr(local.recentVocabModes)],x=>String(x),24);o.sessions=Math.max(Number(remote.sessions||0),Number(local.sessions||0));o.streak=Math.max(Number(remote.streak||1),Number(local.streak||1));o.lastDay=stampDay(local.lastDay)>=stampDay(remote.lastDay)?local.lastDay:remote.lastDay;o.activeTopic=newerTopic(remote.activeTopic,local.activeTopic)||null;return o}
function libraryOf(x=state){return{materials:arr(x?.materials),customWords:arr(x?.customWords),customTopics:arr(x?.customTopics)}}
function mergeLibrary(remote,local){return{materials:mergeById(remote?.materials,local?.materials,80),customWords:mergeById(remote?.customWords,local?.customWords),customTopics:mergeById(remote?.customTopics,local?.customTopics)}}
function hydrate(){for(const w of arr(state.customWords)){if(typeof WORDS!=='undefined'&&!WORDS.some(x=>String(x.id)===String(w.id)))WORDS.push(w)}}
function mutateState(next,rerender=true){const before=stable(libraryOf(state));for(const k of Object.keys(state))delete state[k];Object.assign(state,next||{});try{localStorage.setItem(KEY,JSON.stringify(state))}catch{}hydrate();if(rerender&&before!==stable(libraryOf(state))){try{renderAll()}catch{}}}
function applyLibrary(lib){const merged=mergeLibrary(lib,libraryOf(state));const changed=stable(merged)!==stable(libraryOf(state));state.materials=merged.materials;state.customWords=merged.customWords;state.customTopics=merged.customTopics;try{localStorage.setItem(KEY,JSON.stringify(state))}catch{}hydrate();if(changed){try{renderAll()}catch{}}return merged}
function setStatus(ok,msg){window.__chineseSync={ok,at:Date.now(),msg};document.documentElement.dataset.cloudSync=ok?'ok':'error'}
async function pushState(){if(busy||!dirty)return;busy=true;try{const r=await fetch(STATE_API,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_rev:rev,state}),cache:'no-store'});const d=await r.json().catch(()=>({}));if(r.status===409){rev=Number(d.rev||0);const merged=mergeState(d.state||{},state);mutateState(merged,false);dirty=true;busy=false;return pushState()}if(r.ok){rev=Number(d.rev||rev);dirty=false;setStatus(true,'progress saved')}else setStatus(false,'progress '+r.status)}catch(e){setStatus(false,'progress offline')}finally{busy=false}}
function scheduleState(){dirty=true;clearTimeout(pushTimer);pushTimer=setTimeout(pushState,500)}
async function pullState(first=false){try{const r=await fetch(STATE_API,{cache:'no-store'});if(!r.ok)return;const d=await r.json();const rr=Number(d.rev||0);if(!d.state){rev=rr;if(first)scheduleState();return}if(!first&&rr<=rev)return;const remote=d.state||{},merged=mergeState(remote,state);rev=rr;const needsPush=stable(merged)!==stable(remote);mutateState(merged,true);if(needsPush)scheduleState();setStatus(true,'progress synced')}catch(e){setStatus(false,'progress offline')}}
async function pushLibrary(){clearTimeout(libTimer);try{const local=libraryOf(state);const r=await fetch(LIB_API,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(local),cache:'no-store'});if(!r.ok){setStatus(false,'library '+r.status);return}const d=await r.json();const merged=applyLibrary(d);if(stable(merged)!==stable(d)){libTimer=setTimeout(pushLibrary,600)}setStatus(true,'library synced')}catch(e){setStatus(false,'library offline')}}
function scheduleLibrary(){clearTimeout(libTimer);libTimer=setTimeout(pushLibrary,350)}
async function pullLibrary(){try{const r=await fetch(LIB_API,{cache:'no-store'});if(!r.ok)return;const remote=await r.json();const local=libraryOf(state),merged=mergeLibrary(remote,local);applyLibrary(merged);if(stable(merged)!==stable(remote))scheduleLibrary();setStatus(true,'library synced')}catch(e){setStatus(false,'library offline')}}
const originalSave=save;save=function(){originalSave();scheduleState();scheduleLibrary()};
async function boot(){await pushLibrary();await pullState(true);await pullLibrary();setInterval(()=>{pullState(false);pullLibrary()},12000);document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden'){pushState();pushLibrary()}else{pullState(false);pullLibrary()}});window.addEventListener('pagehide',()=>{if(dirty){try{fetch(STATE_API,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base_rev:rev,state}),keepalive:true})}catch{}}try{fetch(LIB_API,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(libraryOf(state)),keepalive:true})}catch{}})}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();"""
'''
pat=r'CLOUD_SYNC_JS = r""".*?"""\n\ndef read_sync_state\(\):'
assert re.search(pat,s,flags=re.S)
s=re.sub(pat,cloud+'\ndef read_sync_state():',s,count=1,flags=re.S)

library_helpers=r'''
def read_library():
    try:
        obj=json.loads(LIBRARY_FILE.read_text(encoding="utf-8"))
        if isinstance(obj,dict):
            return {"materials":obj.get("materials") if isinstance(obj.get("materials"),list) else [],"customWords":obj.get("customWords") if isinstance(obj.get("customWords"),list) else [],"customTopics":obj.get("customTopics") if isinstance(obj.get("customTopics"),list) else []}
    except Exception:pass
    return {"materials":[],"customWords":[],"customTopics":[]}

def merge_list_by_id(old,new,limit=None):
    out={}
    order=[]
    for item in (old if isinstance(old,list) else [])+(new if isinstance(new,list) else []):
        if not isinstance(item,dict):continue
        key=item.get("id") or item.get("topicId")
        if key is None:key=json.dumps(item,ensure_ascii=False,sort_keys=True)
        key=str(key)
        if key not in out:order.append(key)
        out[key]=item
    vals=[out[k] for k in order]
    return vals[-limit:] if limit else vals

def merge_library(incoming):
    current=read_library()
    merged={
        "materials":merge_list_by_id(current.get("materials"),incoming.get("materials"),80),
        "customWords":merge_list_by_id(current.get("customWords"),incoming.get("customWords")),
        "customTopics":merge_list_by_id(current.get("customTopics"),incoming.get("customTopics")),
    }
    LIBRARY_FILE.parent.mkdir(parents=True,exist_ok=True)
    tmp=LIBRARY_FILE.with_name(LIBRARY_FILE.name+".tmp")
    tmp.write_text(json.dumps(merged,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    os.replace(tmp,LIBRARY_FILE)
    return merged

'''
marker='def http_json('
assert marker in s
s=s.replace(marker,library_helpers+marker,1)

get_anchor='        if path.rstrip("/")=="/api/state":\n            return self.send_json(200,read_sync_state())\n'
assert get_anchor in s
s=s.replace(get_anchor,get_anchor+'        if path.rstrip("/")=="/api/library":\n            return self.send_json(200,read_library())\n',1)

post_anchor='        if path=="/api/state":\n'
assert post_anchor in s
lib_post='''        if path=="/api/library":
            try:n=int(self.headers.get("Content-Length","0"))
            except:n=0
            if n<=0 or n>MAX_STATE:return self.send_json(413,{"error":"Слишком большая библиотека."})
            try:body=json.loads(self.rfile.read(n).decode("utf-8"))
            except Exception:return self.send_json(400,{"error":"Некорректный JSON библиотеки."})
            if not isinstance(body,dict):return self.send_json(400,{"error":"Библиотека должна быть объектом."})
            return self.send_json(200,merge_library(body))
'''
s=s.replace(post_anchor,lib_post+post_anchor,1)

s=s.replace('ChineseStudy/4.7','ChineseStudy/4.8').replace('Chinese Study 4.7','Chinese Study 4.8').replace('topic-study.js?v=4.7','topic-study.js?v=4.8').replace('cloud-sync.js?v=4.7','cloud-sync.js?v=4.8')
s=s.replace('"version":"4.6"','"version":"4.8"')
p.write_text(s,encoding='utf-8')

m=Path('manifest.txt').read_text(encoding='utf-8').replace('version=4.7','version=4.8')
Path('manifest.txt').write_text(m,encoding='utf-8')
