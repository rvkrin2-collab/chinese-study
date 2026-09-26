#!/usr/bin/env python3
import base64, hashlib, json, os, re, subprocess, tempfile, threading, time, urllib.error, urllib.request, uuid
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

APP = Path(os.environ.get("CHINESE_STUDY_DIR", "/opt/apps/chinese-study")).resolve()
HOST = os.environ.get("CHINESE_STUDY_HOST", "127.0.0.1")
PORT = int(os.environ.get("CHINESE_STUDY_PORT", "8910"))
KEY = os.environ.get("MINIMAX_API_KEY", "").strip()
API_HOST = os.environ.get("MINIMAX_API_HOST", "https://api.minimax.io").rstrip("/")
MODEL = os.environ.get("MINIMAX_MODEL", "MiniMax-M3").strip() or "MiniMax-M3"
TEXT_URL = API_HOST + "/anthropic/v1/messages"
VLM_URL = API_HOST + "/v1/coding_plan/vlm"
MAX_REQUEST = 55 * 1024 * 1024
MAX_FILE = 12 * 1024 * 1024
MAX_BATCH_FILES = 10
MAX_BATCH_BYTES = 30 * 1024 * 1024
MAX_BATCH_PDF_PAGES = 24
STATE_FILE = Path(os.environ.get("CHINESE_STUDY_STATE_FILE", "/var/lib/chinese-study/state.json"))
MAX_STATE = 4 * 1024 * 1024
LIBRARY_FILE = Path(os.environ.get("CHINESE_STUDY_LIBRARY_FILE", "/var/lib/chinese-study/library.json"))
RELEASE_ASSET_BASE = os.environ.get(
    "CHINESE_STUDY_RELEASE_ASSET_BASE",
    "https://raw.githubusercontent.com/rvkrin2-collab/chinese-study/main",
).rstrip("/")
RELEASE_ASSETS = {
    "/curriculum-app.js": "curriculum-app.js",
    "/curriculum/curriculum-v1.json": "curriculum/curriculum-v1.json",
}
RELEASE_ASSET_SHA256 = {
    "curriculum-app.js": "077bd078c020019011da25fb1293e952f8735d2e9378ace72bbbb91725981709",
    "curriculum/curriculum-v1.json": "ba1b707fb436c2f056800214956eba3079fb52f2624031f187078e1464ee5a30",
}

SYSTEM_PROMPT = """Ты методист по китайскому для русскоязычного ученика HSK 1–4.
На входе — текст учебного материала, уже извлечённый из фото/PDF/TXT, и иногда заметка пользователя.
Не придумывай факты о содержании источника и не угадывай неразборчивый текст. Упражнения можно создавать новые по теме и лексике источника.

Верни ТОЛЬКО валидный JSON без markdown:
{"title_cn":"","title_pinyin":"","title_ru":"","summary_ru":"","source_text_cn":"","source_pinyin":"","words":[{"hanzi":"","pinyin":"","translation_ru":"","hsk_level":4,"example_cn":"","example_pinyin":"","example_ru":""}],"grammar":[{"pattern":"","meaning_ru":"","example_cn":"","example_pinyin":"","question":"","options":["","","",""],"answer":""}],"readings":[{"cn":"","pinyin":"","question":"","options":["","","",""],"answer_index":0}],"builds":[{"tokens":[""],"answer":"","pinyin":"","translation_ru":""}],"productions":[{"prompt_ru":"","answers":[""],"pinyin":""}]}.

Правила:
- 10–20 действительно полезных слов/выражений, соответствующих указанному текущему уровню пользователя; не набивай простыми словами ради количества.
- 6–8 разных грамматических заданий.
- 4–5 разных заданий на чтение.
- ровно 6 заданий на порядок слов.
- ровно 6 заданий RU→中文.
- не делай дубликаты и почти одинаковые задания.
- неправильные варианты должны быть правдоподобными для HSK3–4.
- для всех китайских слов, примеров и ответов дай pinyin с тонами.
- hsk_level только 3 или 4.
- grammar.options всегда 4 варианта, answer дословно равен одному из них.
- grammar.options должны быть попарно различными; только один вариант должен удовлетворять проверяемой конструкции.
- readings.options всегда 4 варианта, answer_index 0..3.
- source_text_cn сохраняй максимально близко к источнику.
- source_pinyin должен соответствовать source_text_cn.
"""

VISION_PROMPT = """Точно прочитай этот китайский учебный материал. Извлеки весь полезный текст:
китайские слова, предложения, заголовки, вопросы, варианты ответов, подписи и краткие русские/английские пояснения, если они есть.
Сохраняй порядок и формулировки. Не выдумывай неразборчивое. Ответь только распознанным содержанием обычным текстом, без анализа и markdown."""

TOPIC_STUDY_JS = r"""(()=>{
const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
function saveState(){try{localStorage.setItem(KEY,JSON.stringify(state))}catch{}}
function topic(id){
  if(!id)return null;
  const custom=(state.customTopics||[]).find(t=>String(t.id)===String(id));
  if(custom)return custom;
  try{return (typeof TOPICS!=="undefined"&&TOPICS[id])||null}catch{return null}
}
function topicWords(t){return (t?.wordIds||[]).map(id=>WORDS.find(w=>String(w.id)===String(id))).filter(Boolean)}
function shuffled(a){return [...(a||[])].sort(()=>Math.random()-.5)}
function priority(w){const s=ws(w.id);return(!s.seen?1000:0)+((s.due||0)<=now()?300:0)+(s.lapses||0)*30-(s.reps||0)+Math.random()}

const normalBuild=buildSession;
buildSession=function(){
  const id=state?.strictTopicNext;
  if(!id)return normalBuild();
  state.strictTopicNext=null;saveState();
  const t=topic(id);if(!t)return normalBuild();

  const vw=topicWords(t).sort((a,b)=>priority(b)-priority(a)).slice(0,5);
  const li=shuffled(vw).slice(0,2);
  const gr=shuffled(t.grammar||[]).slice(0,3);
  const rd=shuffled(t.readings||[]).slice(0,2);
  const bu=shuffled(t.builds||[]).slice(0,3);
  const pr=shuffled(t.productions||[]).slice(0,2);

  lessonSteps=[
    vw[0]&&{type:"vocab",w:vw[0]},
    gr[0]&&{type:"grammar",x:gr[0]},
    li[0]&&{type:"listening",w:li[0]},
    vw[1]&&{type:"vocab",w:vw[1]},
    rd[0]&&{type:"reading",x:rd[0]},
    bu[0]&&{type:"sentence",x:bu[0]},
    vw[2]&&{type:"vocab",w:vw[2]},
    gr[1]&&{type:"grammar",x:gr[1]},
    li[1]&&{type:"listening",w:li[1]},
    vw[3]&&{type:"vocab",w:vw[3]},
    pr[0]&&{type:"production",x:pr[0]},
    bu[1]&&{type:"sentence",x:bu[1]},
    vw[4]&&{type:"vocab",w:vw[4]},
    rd[1]&&{type:"reading",x:rd[1]},
    gr[2]&&{type:"grammar",x:gr[2]},
    pr[1]&&{type:"production",x:pr[1]},
    bu[2]&&{type:"sentence",x:bu[2]}
  ].filter(Boolean);
  lessonPos=0;
  lessonStats={vocab:0,listening:0,grammar:0,reading:0,sentence:0,production:0};
};

window.studyMaterialOnly=function(id){
  const t=topic(id);if(!t)return;
  state.strictTopicNext=id;
  state.activeTopic={id,started:now(),until:now()+3*DAY};
  saveState();openSession();
};

window.studyLegacyMaterial=function(mid){
  const m=(state.materials||[]).find(x=>String(x.id)===String(mid));if(!m)return;
  const ids=(m.wordIds||[]).filter(id=>WORDS.some(w=>String(w.id)===String(id)));
  if(!ids.length)return reanalyzeLegacyMaterial(mid);
  const id="legacy_"+String(m.id).replace(/[^a-zA-Z0-9_-]/g,"_");
  let t=topic(id);
  if(!t){
    t={id,title:m.title||"Сохранённый материал",pinyin:"",ru:"",wordIds:ids,grammar:[],readings:[],builds:[],productions:[],sourceText:m.preview||"",sourcePinyin:""};
    if(!Array.isArray(state.customTopics))state.customTopics=[];
    state.customTopics.push(t);saveState();
  }
  studyMaterialOnly(id);
};

window.reanalyzeLegacyMaterial=function(mid){
  const m=(state.materials||[]).find(x=>String(x.id)===String(mid));
  const btn=document.getElementById("showMaterialAdd");if(btn)btn.click();
  setTimeout(()=>{
    const ta=document.getElementById("aimText")||document.getElementById("materialText");
    if(ta&&m?.preview)ta.value=m.preview;
  },80);
};

window.toggleMaterialSource=function(id,btn){
  const sid="study-src-"+String(id).replace(/[^a-zA-Z0-9_-]/g,"_");
  const box=document.getElementById(sid);if(!box)return;
  box.classList.toggle("hidden");
  btn.textContent=box.classList.contains("hidden")?"Показать текст":"Скрыть текст";
};

function materialCards(holder,items){
  const raw=[...holder.querySelectorAll("article, .card, .topiccard, [data-material-id]")];
  const unique=[...new Set(raw)].filter(el=>
    !el.classList.contains("saved-material-help") &&
    !el.classList.contains("sectionhead") &&
    !el.closest(".sourcebox") &&
    !el.closest("#topic-shopping")
  );
  const matched=unique.filter(el=>{
    const text=(el.textContent||"").trim();
    return items.some(m=>(m.title&&text.includes(m.title)) || (m.fileName&&text.includes(m.fileName)));
  });
  return matched.length?matched:unique.filter(el=>el.parentElement===holder || el.parentElement?.classList.contains("materials-grid"));
}

function enhance(){
  const holder=$("#customMaterials");if(!holder)return;
  const items=[...(state.materials||[])].reverse();

  const h=$(".sectionhead h2",holder);if(h)h.textContent="Сохранённые материалы";
  let help=$(".saved-material-help",holder);
  if(!help){
    help=document.createElement("div");
    help.className="topic-study-note saved-material-help";
    help.innerHTML="<b>Как изучать:</b> у каждого материала есть кнопка запуска. Новый материал открывается отдельным уроком только по нему.";
    const head=$(".sectionhead",holder);
    if(head)head.after(help);else holder.prepend(help);
  }

  const cards=materialCards(holder,items);
  cards.forEach((card,i)=>{
    const text=card.textContent||"";
    const m=items.find(x=>x.title&&text.includes(x.title)) || items.find(x=>x.fileName&&text.includes(x.fileName)) || items[i];
    if(!m)return;

    const id=m.topicId,t=topic(id);
    let actions=$(".custom-topic-actions",card);
    if(!actions){
      actions=document.createElement("div");
      actions.className="custom-topic-actions";
      actions.style.cssText="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap";
      card.appendChild(actions);
    }
    $$(".study-only-btn,.legacy-study-btn,.reanalyze-btn,.source-study-btn",actions).forEach(x=>x.remove());

    if(id&&t){
      const b=document.createElement("button");
      b.className="primary study-only-btn";
      b.textContent=t.studyMode==="words"?"Изучать слова":"Изучать этот материал";
      b.onclick=()=>studyMaterialOnly(id);
      actions.prepend(b);

      if(t.sourceText){
        const sb=document.createElement("button");
        sb.className="ghost source-study-btn";
        sb.textContent="Показать текст";
        sb.onclick=()=>toggleMaterialSource(id,sb);
        actions.appendChild(sb);

        const sid="study-src-"+String(id).replace(/[^a-zA-Z0-9_-]/g,"_");
        let box=document.getElementById(sid);
        if(!box){
          box=document.createElement("div");
          box.id=sid;box.className="sourcebox hidden";
          const label=document.createElement("div");label.className="tiny";label.textContent="原文 · материал";
          const cn=document.createElement("div");cn.className="cntext";cn.style.whiteSpace="pre-wrap";cn.textContent=t.sourceText;
          box.append(label,cn);
          if(t.sourcePinyin){
            const py=document.createElement("div");py.className="reading-pinyin";py.style.cssText="margin-top:10px;white-space:pre-wrap";py.textContent=t.sourcePinyin;box.appendChild(py);
          }
          actions.after(box);
        }
      }
    } else if((m.wordIds||[]).length){
      const b=document.createElement("button");
      b.className="primary legacy-study-btn";b.textContent="Изучать слова из текста";b.onclick=()=>studyLegacyMaterial(m.id);actions.prepend(b);
    } else {
      const b=document.createElement("button");
      b.className="primary reanalyze-btn";b.textContent="Переразобрать через MiniMax";b.onclick=()=>reanalyzeLegacyMaterial(m.id);actions.prepend(b);
    }
  });
}

const oldRender=renderMaterials;
renderMaterials=function(){oldRender();setTimeout(enhance,0)};
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",()=>setTimeout(enhance,0));
else setTimeout(enhance,0);
})();"""

CLOUD_SYNC_JS = r"""(()=>{
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
function mergeCurriculum(r,l){r=r&&typeof r==='object'?r:{};l=l&&typeof l==='object'?l:{};const newer=Number(l.updatedAt||0)>=Number(r.updatedAt||0)?l:r,older=newer===l?r:l,out={...older,...newer};out.schemaVersion=Math.max(Number(r.schemaVersion||0),Number(l.schemaVersion||0),1);out.completed={...(r.completed||{})};for(const [id,ts] of Object.entries(l.completed||{}))out.completed[id]=Math.max(Number(out.completed[id]||0),Number(ts||0));out.lessonResults={...(r.lessonResults||{})};for(const [id,v] of Object.entries(l.lessonResults||{})){if(Number(v?.completedAt||0)>=Number(out.lessonResults[id]?.completedAt||0))out.lessonResults[id]=v}out.grammarSrs=mergeWords(r.grammarSrs,l.grammarSrs);out.updatedAt=Math.max(Number(r.updatedAt||0),Number(l.updatedAt||0));return out}
function mergeState(remote,local){remote=remote&&typeof remote==='object'?remote:{};local=local&&typeof local==='object'?local:{};const o={...remote,...local};o.words=mergeWords(remote.words,local.words);o.history=mergeHistory(remote.history,local.history);o.skills=mergeSkills(remote.skills,local.skills);o.materials=mergeById(remote.materials,local.materials,80);o.customWords=mergeById(remote.customWords,local.customWords);o.customTopics=mergeById(remote.customTopics,local.customTopics);o.curriculum=mergeCurriculum(remote.curriculum,local.curriculum);o.recentTasks=uniq([...arr(remote.recentTasks),...arr(local.recentTasks)],x=>String(x),50);o.recentVocabModes=uniq([...arr(remote.recentVocabModes),...arr(local.recentVocabModes)],x=>String(x),24);o.sessions=Math.max(Number(remote.sessions||0),Number(local.sessions||0));o.streak=Math.max(Number(remote.streak||1),Number(local.streak||1));o.lastDay=stampDay(local.lastDay)>=stampDay(remote.lastDay)?local.lastDay:remote.lastDay;o.activeTopic=newerTopic(remote.activeTopic,local.activeTopic)||null;return o}
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

def http_json(url, payload, headers, timeout=120):
    data=json.dumps(payload,ensure_ascii=False).encode("utf-8")
    req=urllib.request.Request(url,data=data,headers=headers,method="POST")
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:
            obj=json.loads(r.read().decode("utf-8","replace"))
    except urllib.error.HTTPError as e:
        body=e.read().decode("utf-8","replace")[:1200]
        if e.code in (401,403): raise RuntimeError("MiniMax отклонил API-ключ.")
        if e.code==429: raise RuntimeError("MiniMax: превышен лимит или закончилась квота.")
        raise RuntimeError(f"MiniMax API {e.code}: {body}")
    except urllib.error.URLError as e:
        raise RuntimeError("VPS не смог подключиться к MiniMax API.") from e
    except json.JSONDecodeError as e:
        raise RuntimeError("MiniMax вернул ответ не в JSON.") from e
    base=obj.get("base_resp") or {}
    code=base.get("status_code")
    if code not in (None,0):
        if code==1004: raise RuntimeError("MiniMax отклонил API-ключ.")
        raise RuntimeError(f"MiniMax API {code}: {base.get('status_msg') or 'неизвестная ошибка'}")
    return obj

def vlm_read_image(mime, raw, page_label=""):
    if mime not in ("image/jpeg","image/png","image/webp"): mime="image/jpeg"
    payload={"prompt":VISION_PROMPT+(f"\nЭто {page_label}." if page_label else ""),"image_url":f"data:{mime};base64,"+base64.b64encode(raw).decode("ascii")}
    resp=http_json(VLM_URL,payload,{"Authorization":"Bearer "+KEY,"MM-API-Source":"Minimax-MCP","Content-Type":"application/json"},120)
    text=str(resp.get("content") or "").strip()
    if not text: raise RuntimeError("MiniMax VLM не вернул распознанный текст.")
    return text

def pdf_to_images(raw, progress=None):
    if not any((Path(d)/"pdftoppm").is_file() for d in os.environ.get("PATH","").split(":")):
        raise RuntimeError("Для PDF не установлен poppler-utils.")
    if progress: progress("rendering_pdf")
    pages=[]
    with tempfile.TemporaryDirectory(prefix="chinese-pdf-") as td:
        src=Path(td)/"input.pdf";src.write_bytes(raw);prefix=str(Path(td)/"page")
        proc=subprocess.run(["pdftoppm","-jpeg","-f","1","-l","8","-r","130","-scale-to","1800",str(src),prefix],capture_output=True,timeout=60)
        if proc.returncode: raise RuntimeError("Не удалось прочитать PDF.")
        for f in sorted(Path(td).glob("page-*.jpg"))[:8]: pages.append(f.read_bytes())
    if not pages: raise RuntimeError("PDF не содержит доступных страниц.")
    return pages

def parse_model_json(s):
    s=(s or "").strip()
    s=re.sub(r"^```(?:json)?\s*|\s*```$","",s,flags=re.I)
    try:return json.loads(s)
    except json.JSONDecodeError:
        a,b=s.find("{"),s.rfind("}")
        if a>=0 and b>a:return json.loads(s[a:b+1])
        raise RuntimeError("MiniMax вернул некорректный JSON темы.")

def text_analyze(extracted,note="",hsk_level=3):
    try:hsk_level=max(1,min(4,int(hsk_level)))
    except (TypeError,ValueError):hsk_level=3
    user_text=f"Текущий уровень пользователя: HSK {hsk_level}. Собери из этого материала одну общую учебную тему с большим запасом разнообразных упражнений минимум на несколько занятий. Если материал состоит из нескольких файлов, считай их частями одного урока, учитывай порядок файлов и не создавай отдельную тему на каждый файл. Личная тема не должна объявлять новую грамматику частью основной Curriculum.\n\nИЗВЛЕЧЁННЫЙ МАТЕРИАЛ:\n"+extracted[:90000]
    if note:user_text+="\n\nЗАМЕТКА ПОЛЬЗОВАТЕЛЯ:\n"+note[:12000]
    payload={"model":MODEL,"max_tokens":14000,"system":SYSTEM_PROMPT,"messages":[{"role":"user","content":user_text}]}
    resp=http_json(TEXT_URL,payload,{"X-Api-Key":KEY,"Authorization":"Bearer "+KEY,"Content-Type":"application/json","anthropic-version":"2023-06-01"},220)
    parts=[x.get("text","") for x in resp.get("content",[]) if x.get("type")=="text" and x.get("text")]
    if not parts:raise RuntimeError("MiniMax M3 не вернул текстовый результат.")
    out=parse_model_json("\n".join(parts))
    required=["title_cn","title_pinyin","title_ru","summary_ru","source_text_cn","source_pinyin","words","grammar","readings","builds","productions"]
    missing=[k for k in required if k not in out]
    if missing:raise RuntimeError("В ответе MiniMax не хватает полей: "+", ".join(missing))
    return out

def analyze(payload, progress=None):
    def _p(stage, detail=""):
        if progress:
            try: progress(stage, detail)
            except Exception: pass
    if not KEY:raise RuntimeError("На VPS не настроен MINIMAX_API_KEY.")
    note=str(payload.get("text") or "").strip()

    raw_items=payload.get("files")
    items=[]
    if isinstance(raw_items,list) and raw_items:
        if len(raw_items)>MAX_BATCH_FILES:
            raise ValueError(f"Можно загрузить максимум {MAX_BATCH_FILES} файлов за один раз.")
        for item in raw_items:
            if not isinstance(item,dict):raise ValueError("Некорректный список файлов.")
            items.append({
                "filename":str(item.get("filename") or "").strip(),
                "mime_type":str(item.get("mime_type") or "").lower().split(";")[0],
                "data_base64":str(item.get("data_base64") or "")
            })
    else:
        legacy_b64=str(payload.get("data_base64") or "")
        if legacy_b64:
            items=[{
                "filename":str(payload.get("filename") or "").strip(),
                "mime_type":str(payload.get("mime_type") or "").lower().split(";")[0],
                "data_base64":legacy_b64
            }]

    if not note and not items:raise ValueError("Добавь текст, фото или PDF.")

    parts=[]
    total_bytes=0
    pdf_pages_used=0
    file_count=len(items)
    for file_no,item in enumerate(items,1):
        filename=item["filename"] or f"файл {file_no}"
        mime=item["mime_type"]
        b64=item["data_base64"]
        if not b64:continue
        _p("reading_file",f"{file_no}/{file_count} · {filename}")
        try:raw=base64.b64decode(b64,validate=True)
        except Exception as e:raise ValueError(f"Не удалось прочитать файл «{filename}».") from e
        if len(raw)>MAX_FILE:raise ValueError(f"Файл «{filename}» больше 12 МБ.")
        total_bytes+=len(raw)
        if total_bytes>MAX_BATCH_BYTES:raise ValueError("Суммарный размер файлов больше 30 МБ.")

        header=f"--- Файл {file_no} из {file_count}: {filename} ---"
        if mime=="application/pdf" or filename.lower().endswith(".pdf"):
            _p("rendering_pdf",f"{file_no}/{file_count} · {filename}")
            pages=pdf_to_images(raw)
            remaining=MAX_BATCH_PDF_PAGES-pdf_pages_used
            if remaining<=0:
                raise ValueError(f"В одном материале можно обработать не более {MAX_BATCH_PDF_PAGES} PDF-страниц суммарно.")
            if len(pages)>remaining:pages=pages[:remaining]
            pdf_pages_used+=len(pages)
            extracted_pages=[]
            for page_no,page in enumerate(pages,1):
                _p("reading_page",f"{page_no}/{len(pages)}|файл {file_no}/{file_count}: {filename}")
                extracted_pages.append(f"[Страница {page_no}]\\n"+vlm_read_image("image/jpeg",page,f"страница {page_no} файла {filename}"))
            parts.append(header+"\\n"+"\\n".join(extracted_pages))
        elif mime in ("image/jpeg","image/png","image/webp"):
            _p("reading_image",f"{file_no}/{file_count} · {filename}")
            parts.append(header+"\\n"+vlm_read_image(mime,raw,f"файл {filename}"))
        elif mime=="image/gif":
            raise ValueError(f"GIF «{filename}» не поддерживается MiniMax VLM. Сохрани кадр как JPG/PNG/WebP.")
        elif mime.startswith("text/") or mime in ("application/octet-stream","") or filename.lower().endswith(".txt"):
            _p("reading_text",f"{file_no}/{file_count} · {filename}")
            parts.append(header+"\\n"+raw.decode("utf-8","replace")[:90000])
        else:
            raise ValueError(f"Формат файла «{filename}» не поддерживается. Нужны JPG, PNG, WebP, PDF или TXT.")

    extracted="\\n\\n".join(x for x in parts if x.strip())
    if not extracted:extracted,note=note,""
    _p("generating",f"{file_count} файл(ов)" if file_count else "текст")
    return text_analyze(extracted,note,payload.get("hsk_level",3))


# --- async analyze jobs: a single long request was dropping as "failed to fetch";
#     now the POST returns a job id at once and the client polls .../analyze/status
JOBS={}
JOBS_LOCK=threading.Lock()

def _job_gc():
    now=time.time()
    with JOBS_LOCK:
        for k in [k for k,v in JOBS.items() if v.get("finished") and now-v["finished"]>3600]:
            JOBS.pop(k,None)
        if len(JOBS)>60:
            for k in sorted(JOBS,key=lambda k:JOBS[k].get("started",0))[:len(JOBS)-60]:
                JOBS.pop(k,None)

def _run_analyze_job(job_id,payload):
    def progress(stage,detail=""):
        with JOBS_LOCK:
            j=JOBS.get(job_id)
            if j and j["state"]=="running":
                j["stage"],j["detail"],j["updated"]=stage,detail,time.time()
    try:
        result=analyze(payload,progress=progress)
        with JOBS_LOCK:
            j=JOBS.get(job_id)
            if j: j.update(state="done",stage="done",result=result,finished=time.time())
    except ValueError as e:
        with JOBS_LOCK:
            j=JOBS.get(job_id)
            if j: j.update(state="error",error=str(e),kind="user",finished=time.time())
    except Exception as e:
        with JOBS_LOCK:
            j=JOBS.get(job_id)
            if j: j.update(state="error",error=str(e),kind="server",finished=time.time())

def start_analyze_job(payload):
    _job_gc()
    job_id=uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id]={"state":"running","stage":"queued","detail":"","error":"","result":None,
                      "started":time.time(),"updated":time.time(),"finished":0}
    threading.Thread(target=_run_analyze_job,args=(job_id,payload),daemon=True,name=f"analyze-{job_id[:8]}").start()
    return job_id

def analyze_job_status(job_id):
    with JOBS_LOCK:
        j=JOBS.get(job_id)
        if not j: return {"state":"unknown"}
        out={"state":j["state"],"stage":j["stage"],"detail":j["detail"],
             "elapsed_seconds":int(time.time()-j["started"])}
        if j["state"]=="done": out["result"]=j["result"]
        if j["state"]=="error": out["error"],out["kind"]=j["error"],j.get("kind","server")
        return out

def ensure_release_asset(request_path):
    """Backwards-compatible bootstrap for VPSes with the pre-6.0 updater."""
    relative = RELEASE_ASSETS.get(request_path)
    if not relative:
        return None
    target = (APP / relative).resolve()
    if target.is_file() and target.stat().st_size > 100:
        return target
    if APP not in target.parents:
        return None
    url = f"{RELEASE_ASSET_BASE}/{relative}"
    request = urllib.request.Request(url, headers={"User-Agent": "ChineseStudy/6.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(4 * 1024 * 1024)
        if hashlib.sha256(body).hexdigest() != RELEASE_ASSET_SHA256[relative]:
            raise ValueError("release asset checksum mismatch")
        if relative.endswith(".js"):
            text = body.decode("utf-8")
            if "CHINESE_CURRICULUM" not in text or "MiniMax_API_KEY" in text:
                raise ValueError("invalid curriculum client")
        else:
            data = json.loads(body.decode("utf-8"))
            if data.get("version") != "1.0.0" or len(data.get("levels", [])) != 4:
                raise ValueError("invalid curriculum data")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("wb", dir=target.parent, delete=False) as tmp:
            tmp.write(body)
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, target)
        return target
    except Exception as exc:
        print(f"release asset bootstrap failed for {relative}: {exc}", flush=True)
        return None


class Handler(SimpleHTTPRequestHandler):
    server_version="ChineseStudy/6.0"
    def __init__(self,*a,**kw):super().__init__(*a,directory=str(APP),**kw)
    def send_bytes(self,status,body,ctype,cache="no-store"):
        self.send_response(status);self.send_header("Content-Type",ctype);self.send_header("Content-Length",str(len(body)));self.send_header("Cache-Control",cache);self.end_headers();self.wfile.write(body)
    def send_json(self,status,obj):self.send_bytes(status,json.dumps(obj,ensure_ascii=False).encode("utf-8"),"application/json; charset=utf-8")
    def do_GET(self):
        path=self.path.split("?",1)[0]
        if path.rstrip("/")=="/api/health":
            return self.send_json(200,{"ok":True,"version":"6.0","provider":"MiniMax","ai_configured":bool(KEY),"model":MODEL,"vision":"coding_plan/vlm","saved_material_actions":True,"curriculum":"1.0.0"})
        if path.rstrip("/")=="/api/state":
            return self.send_json(200,read_sync_state())
        if path.rstrip("/")=="/api/library":
            return self.send_json(200,read_library())
        if path.rstrip("/")=="/api/materials/analyze/status":
            job_id=self.path.split("job=",1)[1].split("&",1)[0] if "job=" in self.path else ""
            return self.send_json(200,analyze_job_status(job_id))
        if path=="/cloud-sync.js":
            return self.send_bytes(200,CLOUD_SYNC_JS.encode("utf-8"),"application/javascript; charset=utf-8")
        if path=="/topic-study.js":
            return self.send_bytes(200,TOPIC_STUDY_JS.encode("utf-8"),"application/javascript; charset=utf-8")
        if path in RELEASE_ASSETS:
            asset=ensure_release_asset(path)
            if asset:
                ctype="application/javascript; charset=utf-8" if path.endswith(".js") else "application/json; charset=utf-8"
                return self.send_bytes(200,asset.read_bytes(),ctype,"public, max-age=300")
            return self.send_json(503,{"error":"Curriculum asset unavailable"})
        if path in ("/","/index.html"):
            p=APP/"index.html"
            if p.is_file():
                html=p.read_text(encoding="utf-8")
                html=re.sub(r'<script src="topic-study\.js\?v=[^"]+"></script>\s*',"",html)
                html=re.sub(r'<script src="ai-import\.js\?v=[^"]+"></script>\s*',"",html)
                html=re.sub(r'<script src="cloud-sync\.js\?v=[^"]+"></script>\s*',"",html)
                html=re.sub(r'<script src="curriculum-app\.js\?v=[^"]+"></script>\s*',"",html)
                html=html.replace("</body>",'<script src="topic-study.js?v=6.0"></script>\n<script src="ai-import.js?v=6.0"></script>\n<script src="curriculum-app.js?v=6.0"></script>\n<script src="cloud-sync.js?v=6.0"></script>\n</body>')
                return self.send_bytes(200,html.encode("utf-8"),"text/html; charset=utf-8","no-cache")
        return super().do_GET()
    def do_POST(self):
        path=self.path.split("?",1)[0].rstrip("/")
        if path=="/api/library":
            try:n=int(self.headers.get("Content-Length","0"))
            except:n=0
            if n<=0 or n>MAX_STATE:return self.send_json(413,{"error":"Слишком большая библиотека."})
            try:body=json.loads(self.rfile.read(n).decode("utf-8"))
            except Exception:return self.send_json(400,{"error":"Некорректный JSON библиотеки."})
            if not isinstance(body,dict):return self.send_json(400,{"error":"Библиотека должна быть объектом."})
            return self.send_json(200,merge_library(body))
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
        try:n=int(self.headers.get("Content-Length","0"))
        except:n=0
        if n<=0 or n>MAX_REQUEST:return self.send_json(413,{"error":"Слишком большой запрос."})
        try:body=json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:return self.send_json(400,{"error":"Некорректный JSON запроса."})
        if not isinstance(body,dict):return self.send_json(400,{"error":"Некорректный запрос."})
        return self.send_json(202,{"job_id":start_analyze_job(body)})

if __name__=="__main__":
    APP.mkdir(parents=True,exist_ok=True)
    print(f"Chinese Study 6.0 + Curriculum 1.0 + MiniMax on http://{HOST}:{PORT}",flush=True)
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
