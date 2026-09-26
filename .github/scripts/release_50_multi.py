from pathlib import Path

# --- frontend ---
p=Path("ai-import.js")
a=p.read_text(encoding="utf-8")

old_input='<input id="aimFile" type="file" accept="image/png,image/jpeg,image/webp,.pdf,.txt,text/plain"><div class="tiny" style="margin-top:7px">JPG / PNG / WebP / PDF / TXT · до 12 МБ · файл не сохраняется на VPS</div>'
new_input='<input id="aimFile" type="file" multiple accept="image/png,image/jpeg,image/webp,.pdf,.txt,text/plain"><div class="tiny" style="margin-top:7px">Можно выбрать несколько файлов · JPG / PNG / WebP / PDF / TXT · до 12 МБ каждый, до 30 МБ суммарно · максимум 10 файлов</div><div id="aimFileList" class="tiny" style="margin-top:8px;line-height:1.55"></div>'
assert old_input in a, "file input anchor not found"
a=a.replace(old_input,new_input,1)

old_wire="m.querySelector('#aimAnalyze').onclick=analyze;m.querySelectorAll('input[name=\"aimStudyMode\"]').forEach(r=>r.onchange=syncImportMode);syncImportMode();return m"
new_wire="m.querySelector('#aimAnalyze').onclick=analyze;const fi=m.querySelector('#aimFile');if(fi)fi.onchange=renderSelectedFiles;m.querySelectorAll('input[name=\"aimStudyMode\"]').forEach(r=>r.onchange=syncImportMode);syncImportMode();renderSelectedFiles();return m"
assert old_wire in a, "modal wire anchor not found"
a=a.replace(old_wire,new_wire,1)

anchor="function status(t,k='')"
assert anchor in a
helper="""function renderSelectedFiles(){const input=document.getElementById('aimFile'),box=document.getElementById('aimFileList');if(!box)return;const files=[...(input?.files||[])];if(!files.length){box.innerHTML='';return}const total=files.reduce((n,f)=>n+f.size,0);const mb=n=>(n/1024/1024).toFixed(n>=1024*1024?1:2);box.innerHTML='<b>Выбрано: '+files.length+'</b> · '+mb(total)+' МБ<br>'+files.map((f,i)=>(i+1)+'. '+esc(f.name)+' · '+mb(f.size)+' МБ').join('<br>')}
"""
a=a.replace(anchor,helper+anchor,1)

old_labels="const AIM_LABELS={queued:'Файл получен, начинаю…',received:'Файл получен, начинаю…',rendering_pdf:'Готовлю страницы PDF…',reading_page:'Распознаю страницы…',reading_image:'Распознаю изображение…',reading_text:'Читаю текст…',generating:'MiniMax собирает тему и упражнения…',done:'Готово'};"
new_labels="const AIM_LABELS={queued:'Файлы получены, начинаю…',received:'Файл получен, начинаю…',reading_file:'Перехожу к следующему файлу…',rendering_pdf:'Готовлю страницы PDF…',reading_page:'Распознаю страницы…',reading_image:'Распознаю изображение…',reading_text:'Читаю текст…',generating:'MiniMax объединяет материалы в тему…',done:'Готово'};"
assert old_labels in a, "labels anchor not found"
a=a.replace(old_labels,new_labels,1)

progress_start=a.index("  if(stage==='reading_page'&&detail){")
progress_end=a.index("\n  status(",progress_start)
new_progress="""  if(stage==='reading_file'&&detail){label='Обрабатываю '+String(detail);}
  if(stage==='reading_page'&&detail){const bits=String(detail).split('|'),p=bits[0].split('/'),aa=+p[0]||1,bb=+p[1]||1;label=`Распознаю страницу ${aa} из ${bb}${bits[1]?' · '+bits[1]:''}…`;pct=Math.min(90,42+Math.round(aa/Math.max(1,bb)*40));}
  else if(detail&&['reading_image','reading_text','rendering_pdf'].includes(stage)){label+=(detail?' · '+detail:'');}
"""
a=a[:progress_start]+new_progress+a[progress_end:]

start=a.index("async function analyze(){")
end=a.index("\nfunction preview(){",start)
new_analyze=r"""async function analyze(){
  const btn=document.getElementById('aimAnalyze'),files=[...(document.getElementById('aimFile')?.files||[])],text=document.getElementById('aimText').value.trim(),mode=importMode();
  if(!files.length&&!text)return status('Добавь фото, PDF, TXT или вставь текст.','err');
  if(files.length>10)return status('Можно загрузить максимум 10 файлов за один раз.','err');
  const tooBig=files.find(f=>f.size>12*1024*1024);
  if(tooBig)return status('Файл «'+esc(tooBig.name)+'» больше 12 МБ.','err');
  const totalBytes=files.reduce((n,f)=>n+f.size,0);
  if(totalBytes>30*1024*1024)return status('Суммарный размер файлов больше 30 МБ. Уменьши пакет или раздели его на две темы.','err');
  btn.disabled=true;pending=null;document.getElementById('aimPreview').innerHTML='';
  aimProgress('queued','',0);
  try{
    const packed=[];
    for(let i=0;i<files.length;i++){
      const file=files[i];
      status('<div class="aim-prog"><div class="aim-prog-txt">Готовлю файл '+(i+1)+' из '+files.length+': '+esc(file.name)+'</div></div>','busy');
      packed.push({filename:file.name,mime_type:file.type||'',data_base64:await b64(file)});
    }
    const body={text,study_mode:mode,files:packed};
    const s0=await fetch('api/materials/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const sd=await s0.json().catch(()=>({}));
    if(!s0.ok||!sd.job_id)throw Error(sd.error||`Ошибка сервера ${s0.status}`);
    const job=sd.job_id,began=Date.now();let fails=0;
    for(;;){
      await new Promise(r=>setTimeout(r,1500));
      if(Date.now()-began>24*60*1000)throw Error('Слишком долго. Попробуйте уменьшить число PDF-страниц или разделить материал на две темы.');
      let d;
      try{const r=await fetch('api/materials/analyze/status?job='+encodeURIComponent(job),{cache:'no-store'});d=await r.json();fails=0;}
      catch(e){if(++fails>=6)throw Error('Потеряна связь с сервером. Обновите страницу и попробуйте снова — материал не сохранён.');continue;}
      if(d.state==='unknown')throw Error('Сервис перезапустился во время разбора. Начните заново.');
      if(d.state==='error')throw Error(d.error||'Не удалось разобрать материал.');
      if(d.state==='done'){
        const names=files.map(f=>f.name);
        pending={...d.result,_fileNames:names,_fileName:names.join(', '),_studyMode:mode};
        preview();status('Разбор готов. Проверь слова перед добавлением.','ok');break;
      }
      aimProgress(d.stage,d.detail,d.elapsed_seconds||Math.round((Date.now()-began)/1000));
    }
  }catch(e){status(esc(e.message||e),'err');}
  finally{btn.disabled=false;}
}"""
a=a[:start]+new_analyze+a[end:]

start=a.index("function preview(){")
end=a.index("\nfunction confirm(){",start)
pv=a[start:end]
needle="const wordsOnly=x._studyMode==='words';"
assert needle in pv
pv=pv.replace(needle,"const wordsOnly=x._studyMode==='words',sourceFiles=(x._fileNames||[]).filter(Boolean),sourceFilesHtml=sourceFiles.length?'<div class=\"tiny\" style=\"margin:8px 0 12px\"><b>Файлы ('+sourceFiles.length+'):</b> '+sourceFiles.map(esc).join(' · ')+'</div>':'';",1)
needle2="<p>${esc(x.summary_ru)}</p><div class=\"tiny\""
assert needle2 in pv, "preview summary anchor not found"
pv=pv.replace(needle2,"<p>${esc(x.summary_ru)}</p>${sourceFilesHtml}<div class=\"tiny\"",1)
a=a[:start]+pv+a[end:]

old_topic="sourceText:x.source_text_cn,sourcePinyin:x.source_pinyin}"
new_topic="sourceText:x.source_text_cn,sourcePinyin:x.source_pinyin,sourceFiles:[...(x._fileNames||[])]}"
assert old_topic in a, "topic source anchor not found"
a=a.replace(old_topic,new_topic,1)

old_material="fileName:x._fileName||'',studyMode:mode"
new_material="fileName:(x._fileNames||[]).join(', ')||x._fileName||'',fileNames:[...(x._fileNames||[])],studyMode:mode"
assert old_material in a, "material file anchor not found"
a=a.replace(old_material,new_material,1)
p.write_text(a,encoding="utf-8")

# --- backend ---
p=Path("server.py")
s=p.read_text(encoding="utf-8")
assert "MAX_REQUEST = 18 * 1024 * 1024" in s
s=s.replace("MAX_REQUEST = 18 * 1024 * 1024\nMAX_FILE = 12 * 1024 * 1024",
"""MAX_REQUEST = 55 * 1024 * 1024
MAX_FILE = 12 * 1024 * 1024
MAX_BATCH_FILES = 10
MAX_BATCH_BYTES = 30 * 1024 * 1024
MAX_BATCH_PDF_PAGES = 24""",1)

old_user='user_text="Собери из этого материала новую учебную тему с большим запасом разнообразных упражнений минимум на несколько занятий.\\n\\nИЗВЛЕЧЁННЫЙ МАТЕРИАЛ:\\n"+extracted[:90000]'
new_user='user_text="Собери из этого материала одну общую учебную тему с большим запасом разнообразных упражнений минимум на несколько занятий. Если материал состоит из нескольких файлов, считай их частями одного урока, учитывай порядок файлов и не создавай отдельную тему на каждый файл.\\n\\nИЗВЛЕЧЁННЫЙ МАТЕРИАЛ:\\n"+extracted[:90000]'
assert old_user in s, "prompt anchor not found"
s=s.replace(old_user,new_user,1)

start=s.index("def analyze(payload, progress=None):")
end=s.index("\n\n# --- async analyze jobs",start)
new_backend=r'''def analyze(payload, progress=None):
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
    return text_analyze(extracted,note)
'''
s=s[:start]+new_backend+s[end:]

s=s.replace('server_version="ChineseStudy/4.9"','server_version="ChineseStudy/5.0"',1)
s=s.replace('"version":"4.9"','"version":"5.0"',1)
s=s.replace('topic-study.js?v=4.8','topic-study.js?v=5.0')
s=s.replace('cloud-sync.js?v=4.8','cloud-sync.js?v=5.0')
s=s.replace('Chinese Study 4.9 + MiniMax','Chinese Study 5.0 + MiniMax',1)
p.write_text(s,encoding="utf-8")

p=Path("manifest.txt")
m=p.read_text(encoding="utf-8")
assert "version=4.9" in m
p.write_text(m.replace("version=4.9","version=5.0",1),encoding="utf-8")
print("patched 5.0 multi-file import")
