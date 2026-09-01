#!/usr/bin/env python3
import base64,json,mimetypes,os,sys,urllib.error,urllib.request
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from pathlib import Path
APP=Path(os.environ.get('CHINESE_STUDY_DIR','/opt/apps/chinese-study')).resolve()
HOST=os.environ.get('CHINESE_STUDY_HOST','127.0.0.1'); PORT=int(os.environ.get('CHINESE_STUDY_PORT','8910'))
KEY=os.environ.get('OPENAI_API_KEY','').strip(); MODEL=os.environ.get('OPENAI_MODEL','gpt-5.6-luna').strip() or 'gpt-5.6-luna'
MAX=18*1024*1024
PROMPT='''Ты методист по китайскому для русскоязычного ученика HSK3→HSK4. Разбери приложенный учебный материал. Не придумывай содержание источника. Верни ТОЛЬКО JSON без markdown со структурой: {"title_cn":"","title_pinyin":"","title_ru":"","summary_ru":"","source_text_cn":"","source_pinyin":"","words":[{"hanzi":"","pinyin":"","translation_ru":"","hsk_level":4,"example_cn":"","example_pinyin":"","example_ru":""}],"grammar":[{"pattern":"","meaning_ru":"","example_cn":"","example_pinyin":"","question":"","options":["","","",""],"answer":""}],"readings":[{"cn":"","pinyin":"","question":"","options":["","","",""],"answer_index":0}],"builds":[{"tokens":[""],"answer":"","pinyin":"","translation_ru":""}],"productions":[{"prompt_ru":"","answers":[""],"pinyin":""}]}. Выдели 8–20 полезных слов/выражений примерно HSK3–4, 2–6 реально релевантных конструкций и по 2–4 задания каждого типа. Для каждого китайского слова и примера дай pinyin с тонами. В grammar options всегда 4 варианта, answer дословно совпадает с одним из них. В readings options всегда 4 варианта, answer_index 0..3. Если на странице есть ответы ученика, используй их как контекст, но не считай автоматически правильными.'''
def out_text(r):
 t=[]
 for i in r.get('output',[]):
  if i.get('type')=='message':
   for c in i.get('content',[]):
    if c.get('type')=='output_text' and isinstance(c.get('text'),str): t.append(c['text'])
 return '\n'.join(t).strip()
def analyze(p):
 if not KEY: raise RuntimeError('На VPS не настроен OPENAI_API_KEY.')
 text=(p.get('text') or '').strip(); fn=(p.get('filename') or 'material').strip()[:160]; mime=(p.get('mime_type') or '').lower().strip(); b64=(p.get('data_base64') or '').strip()
 if not text and not b64: raise ValueError('Добавь текст, фото или PDF.')
 content=[{'type':'input_text','text':'Разбери этот материал как новую учебную тему. Сохраняй формулировки источника максимально точно.'}]
 if text: content.append({'type':'input_text','text':'Текст пользователя:\n'+text[:50000]})
 if b64:
  if len(b64)>16500000: raise ValueError('Файл слишком большой.')
  mime=mime or mimetypes.guess_type(fn)[0] or 'application/octet-stream'; url=f'data:{mime};base64,{b64}'
  if mime.startswith('image/'): content.append({'type':'input_image','image_url':url,'detail':'high'})
  elif mime=='application/pdf': content.append({'type':'input_file','filename':fn or 'material.pdf','file_data':url})
  elif mime.startswith('text/'):
   try: s=base64.b64decode(b64,validate=True).decode('utf-8','replace')
   except Exception as e: raise ValueError('Не удалось прочитать текстовый файл.') from e
   content.append({'type':'input_text','text':'Содержимое файла:\n'+s[:50000]})
  else: raise ValueError('Поддерживаются изображения, PDF и TXT.')
 body={'model':MODEL,'store':False,'instructions':PROMPT,'input':[{'role':'user','content':content}],'text':{'format':{'type':'json_object'}},'max_output_tokens':7000}
 req=urllib.request.Request('https://api.openai.com/v1/responses',data=json.dumps(body,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+KEY,'Content-Type':'application/json'},method='POST')
 try:
  with urllib.request.urlopen(req,timeout=120) as r: resp=json.loads(r.read().decode())
 except urllib.error.HTTPError as e:
  raw=e.read().decode('utf-8','replace')
  try: msg=json.loads(raw).get('error',{}).get('message') or raw
  except Exception: msg=raw
  if e.code==401: raise RuntimeError('OpenAI API отклонил ключ.')
  if e.code==429: raise RuntimeError('OpenAI API: закончился баланс или превышен лимит.')
  raise RuntimeError(f'OpenAI API {e.code}: {msg[:400]}')
 except urllib.error.URLError as e: raise RuntimeError('VPS не смог подключиться к OpenAI API.') from e
 s=out_text(resp)
 if not s: raise RuntimeError('ИИ не вернул результат разбора.')
 try: d=json.loads(s)
 except Exception as e: raise RuntimeError('ИИ вернул некорректный JSON.') from e
 for k in ['title_cn','title_pinyin','title_ru','summary_ru','source_text_cn','source_pinyin','words','grammar','readings','builds','productions']:
  if k not in d: raise RuntimeError('В ответе ИИ не хватает поля '+k)
 return d
class H(SimpleHTTPRequestHandler):
 server_version='ChineseStudy/3.4'
 def __init__(self,*a,**kw): super().__init__(*a,directory=str(APP),**kw)
 def log_message(self,f,*a): sys.stderr.write('%s - - [%s] %s\n'%(self.address_string(),self.log_date_time_string(),f%a))
 def js(self,status,obj):
  b=json.dumps(obj,ensure_ascii=False).encode(); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(b))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(b)
 def do_GET(self):
  if self.path.rstrip('/')=='/api/health': return self.js(200,{'ok':True,'version':'3.4','ai_configured':bool(KEY),'model':MODEL})
  return super().do_GET()
 def do_POST(self):
  if self.path.rstrip('/')!='/api/materials/analyze': return self.js(404,{'error':'not found'})
  try: n=int(self.headers.get('Content-Length','0'))
  except: n=0
  if n<=0 or n>MAX: return self.js(413,{'error':'Слишком большой запрос.'})
  try: self.js(200,analyze(json.loads(self.rfile.read(n).decode())))
  except ValueError as e: self.js(400,{'error':str(e)})
  except Exception as e: self.js(502,{'error':str(e)})
if __name__=='__main__':
 APP.mkdir(parents=True,exist_ok=True); print(f'Chinese Study on http://{HOST}:{PORT}',flush=True); ThreadingHTTPServer((HOST,PORT),H).serve_forever()
