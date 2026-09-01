#!/usr/bin/env python3
import base64,json,os,re,subprocess,tempfile,urllib.error,urllib.request
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from pathlib import Path
APP=Path(os.environ.get('CHINESE_STUDY_DIR','/opt/apps/chinese-study')).resolve()
HOST=os.environ.get('CHINESE_STUDY_HOST','127.0.0.1'); PORT=int(os.environ.get('CHINESE_STUDY_PORT','8910'))
KEY=os.environ.get('MINIMAX_API_KEY','').strip(); MODEL=os.environ.get('MINIMAX_MODEL','MiniMax-M3').strip() or 'MiniMax-M3'
URL='https://api.minimax.io/anthropic/v1/messages'; MAX=18*1024*1024
PROMPT='''Ты методист по китайскому для русскоязычного ученика HSK3→HSK4. Разбери учебный материал. Не придумывай содержание источника и не угадывай неразборчивый текст. Верни ТОЛЬКО валидный JSON без markdown:
{"title_cn":"","title_pinyin":"","title_ru":"","summary_ru":"","source_text_cn":"","source_pinyin":"","words":[{"hanzi":"","pinyin":"","translation_ru":"","hsk_level":4,"example_cn":"","example_pinyin":"","example_ru":""}],"grammar":[{"pattern":"","meaning_ru":"","example_cn":"","example_pinyin":"","question":"","options":["","","",""],"answer":""}],"readings":[{"cn":"","pinyin":"","question":"","options":["","","",""],"answer_index":0}],"builds":[{"tokens":[""],"answer":"","pinyin":"","translation_ru":""}],"productions":[{"prompt_ru":"","answers":[""],"pinyin":""}]}.
Отбери 8–20 действительно полезных слов/выражений, примерно HSK3–4; 2–5 релевантных конструкций; 1–3 задания на чтение; 2–4 на порядок слов; 2–4 RU→中文. Для всех китайских слов и примеров дай pinyin с тонами. hsk_level только 3 или 4. В grammar options всегда 4 варианта, answer дословно равен одному из них. В readings options всегда 4 варианта, answer_index 0..3. Сохрани полезный исходный китайский текст максимально близко к источнику.'''
def pdf_images(raw):
 if not any((Path(d)/'pdftoppm').is_file() for d in os.environ.get('PATH','').split(':')): raise RuntimeError('Для PDF не установлен poppler-utils.')
 out=[]
 with tempfile.TemporaryDirectory(prefix='chinese-pdf-') as td:
  src=Path(td)/'in.pdf'; src.write_bytes(raw); pref=str(Path(td)/'p')
  p=subprocess.run(['pdftoppm','-jpeg','-f','1','-l','8','-r','130','-scale-to','1800',str(src),pref],capture_output=True,timeout=45)
  if p.returncode: raise RuntimeError('Не удалось прочитать PDF.')
  for f in sorted(Path(td).glob('p-*.jpg'))[:8]: out.append(('image/jpeg',base64.b64encode(f.read_bytes()).decode()))
 if not out: raise RuntimeError('PDF не содержит доступных страниц.')
 return out
def parse_json(s):
 s=(s or '').strip(); s=re.sub(r'^```(?:json)?\s*|\s*```$','',s,flags=re.I)
 try:return json.loads(s)
 except:
  a,b=s.find('{'),s.rfind('}')
  if a>=0 and b>a:return json.loads(s[a:b+1])
  raise RuntimeError('MiniMax вернул некорректный JSON.')
def analyze(p):
 if not KEY: raise RuntimeError('На VPS не настроен MINIMAX_API_KEY.')
 text=str(p.get('text') or '').strip(); mime=str(p.get('mime_type') or '').lower().split(';')[0]; b64=str(p.get('data_base64') or '')
 if not text and not b64: raise ValueError('Добавь текст, фото или PDF.')
 content=[{'type':'text','text':'Разбери этот материал как новую учебную тему.'+(('\n\nЗаметка/текст пользователя:\n'+text[:50000]) if text else '')}]
 if b64:
  try: raw=base64.b64decode(b64,validate=True)
  except: raise ValueError('Не удалось прочитать файл.')
  if len(raw)>12*1024*1024: raise ValueError('Файл больше 12 МБ.')
  imgs=[]
  if mime=='application/pdf': imgs=pdf_images(raw)
  elif mime.startswith('image/'): imgs=[(mime if mime in ('image/jpeg','image/png','image/webp','image/gif') else 'image/jpeg',base64.b64encode(raw).decode())]
  elif mime.startswith('text/') or mime=='application/octet-stream': content[0]['text']+='\n\nТекст из файла:\n'+raw.decode('utf-8','replace')[:50000]
  else: raise ValueError('Поддерживаются изображения, PDF и TXT.')
  for mt,data in imgs: content.append({'type':'image','source':{'type':'base64','media_type':mt,'data':data}})
 body={'model':MODEL,'max_tokens':8000,'system':PROMPT,'messages':[{'role':'user','content':content}]}
 req=urllib.request.Request(URL,data=json.dumps(body,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+KEY,'Content-Type':'application/json'},method='POST')
 try:
  with urllib.request.urlopen(req,timeout=120) as r: resp=json.loads(r.read().decode())
 except urllib.error.HTTPError as e:
  msg=e.read().decode('utf-8','replace')[:500]
  if e.code==401: raise RuntimeError('MiniMax отклонил API-ключ.')
  if e.code==429: raise RuntimeError('MiniMax: превышен лимит или закончились доступные кредиты.')
  raise RuntimeError(f'MiniMax API {e.code}: {msg}')
 except urllib.error.URLError as e: raise RuntimeError('VPS не смог подключиться к MiniMax API.') from e
 txt='\n'.join(x.get('text','') for x in resp.get('content',[]) if x.get('type')=='text').strip()
 if not txt: raise RuntimeError('MiniMax не вернул результат.')
 d=parse_json(txt)
 for k in ['title_cn','title_pinyin','title_ru','summary_ru','source_text_cn','source_pinyin','words','grammar','readings','builds','productions']:
  if k not in d: raise RuntimeError('В ответе MiniMax не хватает поля '+k)
 return d
class H(SimpleHTTPRequestHandler):
 server_version='ChineseStudy/3.5'
 def __init__(self,*a,**kw): super().__init__(*a,directory=str(APP),**kw)
 def js(self,status,obj):
  b=json.dumps(obj,ensure_ascii=False).encode(); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(b))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(b)
 def do_GET(self):
  if self.path.rstrip('/')=='/api/health': return self.js(200,{'ok':True,'version':'3.5','provider':'MiniMax','ai_configured':bool(KEY),'model':MODEL})
  return super().do_GET()
 def do_POST(self):
  if self.path.rstrip('/')!='/api/materials/analyze': return self.js(404,{'error':'not found'})
  try:n=int(self.headers.get('Content-Length','0'))
  except:n=0
  if n<=0 or n>MAX:return self.js(413,{'error':'Слишком большой запрос.'})
  try:return self.js(200,analyze(json.loads(self.rfile.read(n).decode())))
  except ValueError as e:return self.js(400,{'error':str(e)})
  except Exception as e:return self.js(502,{'error':str(e)})
if __name__=='__main__':
 APP.mkdir(parents=True,exist_ok=True); print(f'Chinese Study 3.5 + MiniMax on http://{HOST}:{PORT}',flush=True); ThreadingHTTPServer((HOST,PORT),H).serve_forever()
