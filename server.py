#!/usr/bin/env python3
import base64, json, os, re, subprocess, tempfile, urllib.error, urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

APP = Path(os.environ.get("CHINESE_STUDY_DIR", "/opt/apps/chinese-study")).resolve()
HOST = os.environ.get("CHINESE_STUDY_HOST", "127.0.0.1")
PORT = int(os.environ.get("CHINESE_STUDY_PORT", "8910"))
KEY = os.environ.get("MINIMAX_API_KEY", "").strip()
API_HOST = os.environ.get("MINIMAX_API_HOST", "https://api.minimax.io").rstrip("/")
MODEL = (os.environ.get("MINIMAX_MODEL", "MiniMax-M3").strip() or "MiniMax-M3")
TEXT_URL = API_HOST + "/anthropic/v1/messages"
VLM_URL = API_HOST + "/v1/coding_plan/vlm"
MAX_REQUEST = 18 * 1024 * 1024
MAX_FILE = 12 * 1024 * 1024

SYSTEM_PROMPT = """Ты методист по китайскому для русскоязычного ученика HSK3→HSK4.
На входе — текст учебного материала, уже извлечённый из фото/PDF/TXT, и иногда заметка пользователя.
Не придумывай содержание источника и не угадывай неразборчивый текст.

Верни ТОЛЬКО валидный JSON без markdown:
{
  "title_cn":"",
  "title_pinyin":"",
  "title_ru":"",
  "summary_ru":"",
  "source_text_cn":"",
  "source_pinyin":"",
  "words":[
    {"hanzi":"","pinyin":"","translation_ru":"","hsk_level":4,
     "example_cn":"","example_pinyin":"","example_ru":""}
  ],
  "grammar":[
    {"pattern":"","meaning_ru":"","example_cn":"","example_pinyin":"",
     "question":"","options":["","","",""],"answer":""}
  ],
  "readings":[
    {"cn":"","pinyin":"","question":"","options":["","","",""],"answer_index":0}
  ],
  "builds":[
    {"tokens":[""],"answer":"","pinyin":"","translation_ru":""}
  ],
  "productions":[
    {"prompt_ru":"","answers":[""],"pinyin":""}
  ]
}

Правила:
- 8–20 действительно полезных слов/выражений, примерно HSK3–4.
- 2–5 релевантных грамматических конструкций.
- 1–3 задания на чтение.
- 2–4 задания на порядок слов.
- 2–4 задания RU→中文.
- Для всех китайских слов и примеров дай pinyin с тонами.
- hsk_level только 3 или 4.
- В grammar options всегда 4 варианта, answer дословно равен одному из них.
- В readings options всегда 4 варианта, answer_index 0..3.
- Сохрани полезный исходный китайский текст максимально близко к источнику.
"""

VISION_PROMPT = """Точно прочитай этот китайский учебный материал. Извлеки весь полезный текст: китайские слова, предложения, заголовки, вопросы, варианты ответов, подписи и краткие русские/английские пояснения, если они есть. Сохраняй порядок и формулировки. Не выдумывай неразборчивое. Ответь только распознанным содержанием обычным текстом; без анализа и без markdown."""

def http_json(url, payload, headers, timeout=120):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            obj = json.loads(raw)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:1200]
        if e.code in (401, 403):
            raise RuntimeError("MiniMax отклонил API-ключ.")
        if e.code == 429:
            raise RuntimeError("MiniMax: превышен лимит или закончилась квота.")
        raise RuntimeError(f"MiniMax API {e.code}: {body}")
    except urllib.error.URLError as e:
        raise RuntimeError("VPS не смог подключиться к MiniMax API.") from e
    except json.JSONDecodeError as e:
        raise RuntimeError("MiniMax вернул ответ не в JSON.") from e
    base = obj.get("base_resp") or {}
    code = base.get("status_code")
    if code not in (None, 0):
        msg = base.get("status_msg") or "неизвестная ошибка"
        if code == 1004:
            raise RuntimeError("MiniMax отклонил API-ключ.")
        raise RuntimeError(f"MiniMax API {code}: {msg}")
    return obj

def vlm_read_image(mime, raw, page_label=""):
    if mime not in ("image/jpeg", "image/png", "image/webp"):
        mime = "image/jpeg"
    data_url = f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")
    payload = {
        "prompt": VISION_PROMPT + (f"\nЭто {page_label}." if page_label else ""),
        "image_url": data_url,
    }
    resp = http_json(
        VLM_URL,
        payload,
        {
            "Authorization": "Bearer " + KEY,
            "MM-API-Source": "Minimax-MCP",
            "Content-Type": "application/json",
        },
        timeout=120,
    )
    text = str(resp.get("content") or "").strip()
    if not text:
        raise RuntimeError("MiniMax VLM не вернул распознанный текст.")
    return text

def pdf_to_images(raw):
    if not any((Path(d) / "pdftoppm").is_file() for d in os.environ.get("PATH", "").split(":")):
        raise RuntimeError("Для PDF не установлен poppler-utils.")
    pages = []
    with tempfile.TemporaryDirectory(prefix="chinese-pdf-") as td:
        src = Path(td) / "input.pdf"
        src.write_bytes(raw)
        prefix = str(Path(td) / "page")
        proc = subprocess.run(
            ["pdftoppm", "-jpeg", "-f", "1", "-l", "8", "-r", "130", "-scale-to", "1800", str(src), prefix],
            capture_output=True,
            timeout=60,
        )
        if proc.returncode:
            raise RuntimeError("Не удалось прочитать PDF.")
        for f in sorted(Path(td).glob("page-*.jpg"))[:8]:
            pages.append(f.read_bytes())
    if not pages:
        raise RuntimeError("PDF не содержит доступных страниц.")
    return pages

def parse_model_json(s):
    s = (s or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.I)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        a, b = s.find("{"), s.rfind("}")
        if a >= 0 and b > a:
            return json.loads(s[a:b + 1])
        raise RuntimeError("MiniMax вернул некорректный JSON темы.")

def text_analyze(extracted, note=""):
    user_text = "Собери из этого материала новую учебную тему.\n\nИЗВЛЕЧЁННЫЙ МАТЕРИАЛ:\n" + extracted[:90000]
    if note:
        user_text += "\n\nЗАМЕТКА ПОЛЬЗОВАТЕЛЯ:\n" + note[:12000]
    payload = {
        "model": MODEL,
        "max_tokens": 9000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_text}],
    }
    resp = http_json(
        TEXT_URL,
        payload,
        {
            "X-Api-Key": KEY,
            "Authorization": "Bearer " + KEY,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        },
        timeout=180,
    )
    parts = []
    for item in resp.get("content", []):
        if item.get("type") == "text" and item.get("text"):
            parts.append(item["text"])
    if not parts:
        raise RuntimeError("MiniMax M3 не вернул текстовый результат.")
    out = parse_model_json("\n".join(parts))
    required = [
        "title_cn", "title_pinyin", "title_ru", "summary_ru", "source_text_cn",
        "source_pinyin", "words", "grammar", "readings", "builds", "productions",
    ]
    missing = [k for k in required if k not in out]
    if missing:
        raise RuntimeError("В ответе MiniMax не хватает полей: " + ", ".join(missing))
    return out

def analyze(payload):
    if not KEY:
        raise RuntimeError("На VPS не настроен MINIMAX_API_KEY.")
    note = str(payload.get("text") or "").strip()
    mime = str(payload.get("mime_type") or "").lower().split(";")[0]
    b64 = str(payload.get("data_base64") or "")
    if not note and not b64:
        raise ValueError("Добавь текст, фото или PDF.")

    extracted_parts = []
    if b64:
        try:
            raw = base64.b64decode(b64, validate=True)
        except Exception as e:
            raise ValueError("Не удалось прочитать файл.") from e
        if len(raw) > MAX_FILE:
            raise ValueError("Файл больше 12 МБ.")

        if mime == "application/pdf":
            for i, page in enumerate(pdf_to_images(raw), 1):
                extracted_parts.append(f"--- Страница {i} ---\n" + vlm_read_image("image/jpeg", page, f"страница {i} PDF"))
        elif mime in ("image/jpeg", "image/png", "image/webp"):
            extracted_parts.append(vlm_read_image(mime, raw))
        elif mime == "image/gif":
            raise ValueError("GIF не поддерживается MiniMax VLM. Сохрани кадр как JPG/PNG/WebP.")
        elif mime.startswith("text/") or mime in ("application/octet-stream", ""):
            extracted_parts.append(raw.decode("utf-8", "replace")[:90000])
        else:
            raise ValueError("Поддерживаются JPG, PNG, WebP, PDF и TXT.")

    extracted = "\n\n".join(x for x in extracted_parts if x.strip())
    if not extracted:
        extracted = note
        note = ""
    return text_analyze(extracted, note)

class Handler(SimpleHTTPRequestHandler):
    server_version = "ChineseStudy/3.6"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP), **kwargs)

    def send_json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/") == "/api/health":
            return self.send_json(200, {
                "ok": True,
                "version": "3.6",
                "provider": "MiniMax",
                "ai_configured": bool(KEY),
                "model": MODEL,
                "vision": "coding_plan/vlm",
            })
        return super().do_GET()

    def do_POST(self):
        if self.path.rstrip("/") != "/api/materials/analyze":
            return self.send_json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except Exception:
            n = 0
        if n <= 0 or n > MAX_REQUEST:
            return self.send_json(413, {"error": "Слишком большой запрос."})
        try:
            payload = json.loads(self.rfile.read(n).decode("utf-8"))
            return self.send_json(200, analyze(payload))
        except ValueError as e:
            return self.send_json(400, {"error": str(e)})
        except Exception as e:
            return self.send_json(502, {"error": str(e)})

if __name__ == "__main__":
    APP.mkdir(parents=True, exist_ok=True)
    print(f"Chinese Study 3.6 + MiniMax on http://{HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
