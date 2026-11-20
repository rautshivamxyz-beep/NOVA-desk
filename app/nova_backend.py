#!/usr/bin/env python3
# NOVA Desktop 3.0 - local backend
# Runs on the bundled portable Python. Serves the UI, proxies chat to
# llama-server, and adds NOVA's features: model-driven tool router, wiki/web
# lookup, vector + keyword RAG over your notes and documents, flashcards with
# spaced repetition, exams, reminders, calculator, modes, backup and more.
# Stdlib only (+ bundled pypdf for PDFs).
import os, sys, json, sqlite3, threading, time, re, math, io, zipfile, base64, subprocess
import html as H, urllib.request, urllib.parse, mimetypes, traceback, tempfile, ast, operator, ipaddress, socket, filecmp
from contextlib import contextmanager

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE if os.path.isdir(os.path.join(HERE, "web")) else os.path.dirname(HERE)
WEB  = os.path.join(ROOT, "web")
DATA = os.path.join(ROOT, "data")
MODELS = os.path.join(ROOT, "models")
os.makedirs(DATA, exist_ok=True)
os.makedirs(MODELS, exist_ok=True)
DB      = os.path.join(DATA, "nova.db")
PREFS   = os.path.join(DATA, "prefs.json")
LLAMA   = os.environ.get("NOVA_LLAMA", "http://127.0.0.1:8080")
EMBED   = os.environ.get("NOVA_EMBED", "http://127.0.0.1:8081")
PORT    = int(os.environ.get("NOVA_PORT", "8765"))
UA      = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NOVA-Desktop/3.0"
VERSION = "3.0"
MAX_JSON_BODY = 32 * 1024 * 1024
MAX_BACKUP_BYTES = 100 * 1024 * 1024
MAX_MODEL_BYTES = 64 * 1024 * 1024 * 1024

try:
    from pypdf import PdfReader
    HAVE_PDF = True
except Exception:
    HAVE_PDF = False

# ---------------------------------------------------------------- store
_lock = threading.Lock()

@contextmanager
def db():
    """Yield a SQLite connection and always close it after commit/rollback."""
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        with c:
            yield c
    finally:
        c.close()

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, body TEXT, created REAL, updated REAL);
        CREATE TABLE IF NOT EXISTS memory(id INTEGER PRIMARY KEY AUTOINCREMENT, fact TEXT, source TEXT, created REAL, vec TEXT);
        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(fact);
        CREATE TABLE IF NOT EXISTS docs(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, kind TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY AUTOINCREMENT, doc INTEGER, ord INTEGER, text TEXT, vec TEXT);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text);
        CREATE TABLE IF NOT EXISTS cards(id INTEGER PRIMARY KEY AUTOINCREMENT, q TEXT, a TEXT, interval INTEGER DEFAULT 0, due REAL, reps INTEGER DEFAULT 0, created REAL);
        CREATE TABLE IF NOT EXISTS exams(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, questions TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, due REAL, done INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS fetchlog(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, query TEXT, result TEXT, sources TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS recipes(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, prompt TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS skills(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, trigger TEXT, instruction TEXT, source TEXT, created REAL, uses INTEGER DEFAULT 0);
        """)

def rows(sql, a=()):
    with db() as c: return [dict(r) for r in c.execute(sql, a).fetchall()]
def one(sql, a=()):
    with db() as c:
        r = c.execute(sql, a).fetchone()
        return dict(r) if r else None
def run(sql, a=()):
    with _lock, db() as c:
        return c.execute(sql, a).lastrowid

# ---------------------------------------------------------------- prefs
DEFAULT_PREFS = {"mode": "balanced", "tone": "friendly", "tutor": False,
                 "name": "", "grade": "", "subjects": "", "lang": "auto",
                 "voice": False, "sys": ""}

def get_prefs():
    p = dict(DEFAULT_PREFS)
    try:
        with open(PREFS, encoding="utf-8") as f:
            p.update(json.load(f))
    except Exception:
        pass
    return p

def set_prefs(patch):
    p = get_prefs()
    p.update(patch or {})
    with open(PREFS, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=1)
    return p

# ---------------------------------------------------------------- http helpers
def http_get(url, timeout=20, headers=None):
    h = {"User-Agent": UA, "Accept": "*/*"}
    if headers: h.update(headers)
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout) as r:
        raw = r.read(); enc = r.headers.get("Content-Type", "")
    m = re.search(r"charset=([\w-]+)", enc, re.I)
    return raw.decode(m.group(1) if m else "utf-8", "ignore")

def http_json(url, obj, timeout=900):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))

def strip_html(s):
    s = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?is)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>", "\n", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = H.unescape(s)
    s = re.sub(r"[ \t\xa0]+", " ", s)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", s).strip()

# ---------------------------------------------------------------- embeddings
_embed_ok = {"v": None, "checked": 0.0}

def embed_available():
    # A failed probe is temporary while llama-server is still starting. Retry it
    # periodically rather than permanently disabling semantic search.
    if _embed_ok["v"] is None or (not _embed_ok["v"] and time.time() - _embed_ok["checked"] > 15):
        try:
            http_json(EMBED + "/v1/embeddings", {"input": "ping"}, timeout=5)
            _embed_ok["v"] = True
        except Exception:
            _embed_ok["v"] = False
        _embed_ok["checked"] = time.time()
    return bool(_embed_ok["v"])

def embed(texts):
    if isinstance(texts, str): texts = [texts]
    if not texts or not embed_available(): return None
    try:
        j = http_json(EMBED + "/v1/embeddings", {"input": texts}, timeout=120)
        return [d["embedding"] for d in j.get("data", [])]
    except Exception:
        _embed_ok.update(v=False, checked=time.time())
        return None

def cos(a, b):
    s = na = nb = 0.0
    for x, y in zip(a, b):
        s += x * y; na += x * x; nb += y * y
    return s / ((na ** .5) * (nb ** .5) + 1e-9)

def vec_search(table, qtext, k=6, idcol="id", textcol="text", where=""):
    """vector search over rows that have a vec column; returns rows with _score"""
    qv = embed(qtext)
    if not qv: return None
    qv = qv[0]
    sql = "SELECT %s AS rid, %s AS txt, vec FROM %s WHERE vec IS NOT NULL" % (idcol, textcol, table)
    if where: sql += " AND " + where
    try:
        cand = rows(sql)
    except Exception:
        return None
    scored = []
    for r in cand:
        try:
            v = json.loads(r["vec"])
        except Exception:
            continue
        scored.append((cos(qv, v), r["txt"], r["rid"]))
    scored.sort(reverse=True)
    return [{"text": t, "id": i, "score": round(s, 4)} for s, t, i in scored[:k]]

# ---------------------------------------------------------------- memory
def remember(fact, source="chat"):
    fact = (fact or "").strip()
    if len(fact) < 4: return None
    v = embed(fact)
    rid = run("INSERT INTO memory(fact, source, created, vec) VALUES(?,?,?,?)",
              (fact, source, time.time(), json.dumps(v[0]) if v else None))
    run("INSERT INTO memory_fts(rowid, fact) VALUES(?,?)", (rid, fact))
    return rid

def recall(query, limit=6):
    got = vec_search("memory", query, limit, "id", "fact")
    if got:
        return [{"id": g["id"], "fact": g["text"], "source": "memory", "score": g["score"]} for g in got]
    q = re.sub(r"[^0-9A-Za-z\u0900-\u097F ]+", " ", query or "").strip()
    terms = " OR ".join('"%s"' % t for t in q.split() if len(t) > 2)
    if not terms: return []
    try:
        return rows("""SELECT m.id, m.fact, m.source FROM memory_fts f JOIN memory m ON m.id=f.rowid
                       WHERE memory_fts MATCH ? ORDER BY rank LIMIT ?""", (terms, limit))
    except Exception:
        return []

# ---------------------------------------------------------------- docs (knowledge base)
def chunk_text(t, size=900, overlap=150):
    t = re.sub(r"[ \t]+", " ", t or "").strip()
    paras = [p.strip() for p in re.split(r"\n\s*\n", t) if p.strip()]
    out, buf = [], ""
    for p in paras:
        if len(buf) + len(p) + 1 <= size:
            buf = (buf + "\n" + p).strip()
        else:
            if buf: out.append(buf)
            if len(p) <= size:
                buf = p
            else:
                for i in range(0, len(p), size - overlap):
                    out.append(p[i:i + size])
                buf = ""
    if buf: out.append(buf)
    return [c for c in out if len(c) > 40]

def pdf_text(b):
    if not HAVE_PDF: return ""
    try:
        r = PdfReader(io.BytesIO(b))
        parts = []
        for i, p in enumerate(r.pages[:400]):
            parts.append((p.extract_text() or "") + "\n\n- page %d -\n" % (i + 1))
        return "\n".join(parts)
    except Exception:
        return ""

def ingest(name, text, kind="text"):
    did = run("INSERT INTO docs(name, kind, created) VALUES(?,?,?)", (name, kind, time.time()))
    chunks = chunk_text(text)
    vs = embed(chunks) if chunks else None
    for i, ch in enumerate(chunks):
        vec = json.dumps(vs[i]) if vs and i < len(vs) else None
        cid = run("INSERT INTO chunks(doc, ord, text, vec) VALUES(?,?,?,?)", (did, i, ch, vec))
        run("INSERT INTO chunks_fts(rowid, text) VALUES(?,?)", (cid, ch))
    return {"id": did, "name": name, "chunks": len(chunks)}

def doc_search(query, k=6):
    got = vec_search("chunks", query, k, "id", "text")
    if got:
        return [{"text": g["text"], "score": g["score"]} for g in got]
    q = re.sub(r"[^0-9A-Za-z\u0900-\u097F ]+", " ", query or "").strip()
    terms = " OR ".join('"%s"' % t for t in q.split() if len(t) > 2)
    if not terms: return []
    try:
        return [{"text": r["text"], "score": 0} for r in rows(
            "SELECT text FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?", (terms, k))]
    except Exception:
        return []

# ---------------------------------------------------------------- lookup
def ddg_search(q, n=5):
    try:
        page = http_get("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(q), timeout=20)
    except Exception:
        return []
    out = []
    for m in re.finditer(r'(?is)<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page):
        href, title = m.group(1), strip_html(m.group(2))
        if "uddg=" in href:
            try: href = urllib.parse.unquote(re.search(r"uddg=([^&]+)", href).group(1))
            except Exception: pass
        if href.startswith("//"): href = "https:" + href
        if not href.startswith("http") or "duckduckgo.com" in href: continue
        out.append({"title": title, "url": href})
        if len(out) >= n: break
    return out

def _public_web_url(url):
    """Return true only for public HTTP(S) URLs (prevents local-network SSRF)."""
    try:
        u = urllib.parse.urlsplit(url)
        if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
            return False
        host = u.hostname.rstrip(".").lower()
        if host in ("localhost", "localhost.localdomain"):
            return False
        try:
            ips = [ipaddress.ip_address(host)]
        except ValueError:
            ips = [ipaddress.ip_address(x[4][0]) for x in socket.getaddrinfo(host, u.port or (443 if u.scheme == "https" else 80))]
        return bool(ips) and all(ip.is_global for ip in ips)
    except Exception:
        return False

def read_page(url, limit=5000):
    if not _public_web_url(url): return ""
    try: page = http_get(url, timeout=20)
    except Exception: return ""
    return re.sub(r"\n{3,}", "\n\n", strip_html(page))[:limit]

def wiki_lookup(q):
    try:
        api = ("https://en.wikipedia.org/w/api.php?action=query&format=json&generator=search"
               "&gsrsearch=%s&gsrlimit=1&prop=extracts&explaintext=1&exintro=1&redirects=1")
        j = json.loads(http_get(api % urllib.parse.quote(q), timeout=20))
        for p in ((j.get("query") or {}).get("pages") or {}).values():
            ext = (p.get("extract") or "").strip()
            if ext and "may refer to" not in ext.lower()[:200]:
                return "SOURCE: Wikipedia - %s\n%s" % (p.get("title", q), ext[:4000])
    except Exception:
        pass
    return ""

def web_lookup(q):
    hits = ddg_search(q, 5)
    if not hits:
        w = wiki_lookup(q)
        return (w, []) if w else ("", [])
    srcs, parts = [], []
    for h in hits[:3]:
        body = read_page(h["url"], 4000)
        if len(body) < 200: continue
        srcs.append({"title": h["title"], "url": h["url"]})
        parts.append("SOURCE: %s (%s)\n%s" % (h["title"], h["url"], body))
        if len("".join(parts)) > 9000: break
    return ("\n\n".join(parts), srcs)

def log_fetch(kind, query, result, sources):
    try:
        run("INSERT INTO fetchlog(kind, query, result, sources, created) VALUES(?,?,?,?,?)",
            (kind, query, (result or "")[:300], json.dumps(sources or []), time.time()))
    except Exception:
        pass

# ---------------------------------------------------------------- calculator
def calculator(expr):
    """Evaluate a small arithmetic grammar without Python eval or unbounded powers."""
    raw = (expr or "").strip().replace("^", "**").replace("×", "*").replace("÷", "/").replace("−", "-")
    if not raw or len(raw) > 160 or not re.fullmatch(r"[0-9+\-*/().%\s]+", raw):
        return ""
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: None,
           ast.USub: operator.neg, ast.UAdd: operator.pos}
    def visit(node):
        if isinstance(node, ast.Expression): return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            if abs(node.value) > 10**12: raise ValueError("number too large")
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow):
                if abs(right) > 12 or abs(left) > 10**6: raise ValueError("power too large")
                value = left ** right
            else:
                value = ops[type(node.op)](left, right)
            if not math.isfinite(float(value)) or abs(value) > 10**15:
                raise ValueError("result too large")
            return value
        if isinstance(node, ast.UnaryOp) and type(node.op) in ops:
            return ops[type(node.op)](visit(node.operand))
        raise ValueError("unsupported expression")
    try:
        tree = ast.parse(raw, mode="eval")
        if sum(1 for _ in ast.walk(tree)) > 80: return ""
        val = visit(tree)
        if isinstance(val, float) and val.is_integer(): val = int(val)
        return "%s = %s" % (raw, val)
    except Exception:
        return ""

CALC_RE = re.compile(r"(?:what(?:'s| is)|calculate|compute|solve|how much is)\s*([0-9][0-9+\-*/^%(). ]{2,})", re.I)

# ---------------------------------------------------------------- router
WEB_HINTS  = ["search the web","search online","google","web search","look it up","online","internet","latest","recent","news","today","current","right now","as of","price","weather","score","match","stock","kya hua","aaj","abhi","taza","taaza"]
MEM_HINTS  = ["my notes","mera notes","mere notes","my reminders","my memory","what do you remember","do you remember","yaad hai","yaad karo","remember when","save this","note this","yaad rakho"]
DOC_HINTS  = ["my document","my documents","my pdf","the pdf","my book","in the book","my notes say","from my notes","mere notes me","mere documents","according to my"]
FACT_HINTS = ["who","what","when","where","which","whom","whose","kaun","kya","kab","kahan","kis","history","meaning","capital","born","died","founded","invented","discovered","define","explain","difference between","formula","summary of"]
TOOLS = ("web", "wiki", "docs", "memory", "calc", "none")

PLAN_PROMPT = ("You are a tool router. Reply with EXACTLY one word from this list and nothing else:\n"
               "web    - needs live/current info from the internet (news, prices, recent events)\n"
               "wiki   - a general factual question (people, places, science, history, definitions)\n"
               "docs   - answerable from the user's OWN documents/notes\n"
               "memory - about the user personally (their preferences, what they told you before)\n"
               "calc   - a maths calculation\n"
               "none   - everything else (writing, opinions, coding, chit-chat)")

def plan(msg, has_docs):
    m = (msg or "").lower()
    if CALC_RE.search(msg): return "calc"
    if any(h in m for h in MEM_HINTS): return "memory"
    if any(h in m for h in DOC_HINTS) and has_docs: return "docs"
    if any(h in m for h in WEB_HINTS): return "web"
    looks_q = ("?" in msg) or any(h in m for h in FACT_HINTS) or len(m.split()) < 9
    if looks_q:
        try:
            cat = llm_once([{"role": "system", "content": PLAN_PROMPT},
                            {"role": "user", "content": msg}], max_tokens=6).strip().lower()
            for t in TOOLS:
                if t in cat: return t
        except Exception:
            pass
    if any(h in m for h in FACT_HINTS): return "wiki"
    return "none"

# ---------------------------------------------------------------- prompt
MODE_FRAG = {
    "concise":  "Be brief - answer in the fewest words that fully answer. No preamble.",
    "balanced": "Be clear and complete, in short paragraphs.",
    "detailed": "Be thorough - explain fully, with context, examples and structure.",
    "tutor":    "Teach step by step. Break the idea down, check understanding with a question at the end.",
    "exam":     "Answer like a model exam answer: crisp points, key terms, exam-ready.",
}
TONE_FRAG = {
    "friendly": "Warm and encouraging.",
    "neutral":  "Neutral and factual.",
    "formal":   "Formal and precise.",
}

def build_system(kind, context, mem, prefs, doc_hits=None, skill=None):
    s = ["You are NOVA, a private offline assistant running on the user's own computer.",
         "Answer in the user's language (English, Hindi or Hinglish - match them).",
         MODE_FRAG.get(prefs.get("mode", "balanced"), MODE_FRAG["balanced"]),
         TONE_FRAG.get(prefs.get("tone", "friendly"), TONE_FRAG["friendly"])]
    if prefs.get("tutor"): s.append(MODE_FRAG["tutor"])
    who = []
    if prefs.get("name"): who.append("Their name is %s." % prefs["name"])
    if prefs.get("grade"): who.append("They are in %s." % prefs["grade"])
    if prefs.get("subjects"): who.append("Their subjects: %s." % prefs["subjects"])
    if who: s.append("ABOUT THE USER: " + " ".join(who))
    if prefs.get("sys"): s.append("USER'S OWN INSTRUCTION (follow it): " + prefs["sys"])
    s.append("GROUNDING: if a REFERENCE block is given, base the answer on it and prefer it over memory. "
             "If asked for facts and no reference is given and you are not sure, say you could not find a "
             "reliable source and offer to search - never invent facts, dates, numbers or names.")
    if skill:
        s.append("YOUR OWN LEARNED SKILL - follow it for this request:\n" + skill["instruction"].replace("{q}", ""))
    if mem:
        s.append("WHAT YOU REMEMBER ABOUT THE USER:\n" + "\n".join("- " + m["fact"] for m in mem))
    if doc_hits:
        s.append("FROM THE USER'S OWN DOCUMENTS:\n" + "\n---\n".join(d["text"] for d in doc_hits))
    if context:
        s.append("REFERENCE (from the " + ("web" if kind == "web" else "Wikipedia") + "):\n" + context)
    return "\n\n".join(s)

def build_messages(history, msg, kind, context, mem, prefs, doc_hits=None, skill=None):
    msgs = [{"role": "system", "content": build_system(kind, context, mem, prefs, doc_hits, skill)}]
    for m in history[-24:]:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            msgs.append({"role": m["role"], "content": m["content"]})
    msgs.append({"role": "user", "content": msg})
    return msgs

def llm_stream(messages):
    req = urllib.request.Request(LLAMA + "/v1/chat/completions",
        data=json.dumps({"messages": messages, "stream": True, "temperature": 0.7, "max_tokens": 1024}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        for raw in r:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"): continue
            d = line[5:].strip()
            if d == "[DONE]": break
            try:
                t = (json.loads(d)["choices"][0].get("delta") or {}).get("content")
                if t: yield t
            except Exception: continue

def llm_once(messages, max_tokens=512):
    j = http_json(LLAMA + "/v1/chat/completions",
                  {"messages": messages, "stream": False, "temperature": 0.6, "max_tokens": max_tokens})
    return (j["choices"][0]["message"]["content"] or "").strip()

def llm_json(prompt, max_tokens=1200):
    out = llm_once([{"role": "user", "content": prompt}], max_tokens)
    out = re.sub(r"^```(?:json)?|```$", "", out.strip(), flags=re.M).strip()
    m = re.search(r"[\[{].*[\]}]", out, re.S)
    return json.loads(m.group(0) if m else out)

# ---------------------------------------------------------------- server
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def _bytes(self, b, ctype):
        self.send_response(200); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def _read(self):
        n = int(self.headers.get("Content-Length") or 0)
        limit = 140 * 1024 * 1024 if self.path.startswith("/api/restore") else MAX_JSON_BODY
        if n > limit:
            raise ValueError("Backup request is too large (140 MB maximum)." if limit > MAX_JSON_BODY else "Request is too large (32 MB maximum).")
        if not n: return {}
        raw = self.rfile.read(n)
        if len(raw) != n: raise ValueError("Incomplete request body.")
        return json.loads(raw.decode("utf-8"))

    # -------- GET
    def _local_request(self):
        try:
            h = urllib.parse.urlsplit("//" + (self.headers.get("Host") or ""))
            if h.hostname not in ("127.0.0.1", "localhost") or h.port != PORT:
                return False
            origin = self.headers.get("Origin")
            if origin:
                u = urllib.parse.urlsplit(origin)
                if u.scheme != "http" or u.hostname not in ("127.0.0.1", "localhost") or u.port != PORT:
                    return False
            return True
        except Exception:
            return False

    def do_GET(self):
        if not self._local_request(): return self._json({"error": "Local requests only."}, 403)
        _touch()
        u = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(u.query); p = u.path
        try:
            if p == "/api/health":
                ok = False
                try: http_get(LLAMA + "/health", timeout=4); ok = True
                except Exception: ok = False
                return self._json({"ok": True, "engine": ok, "embed": embed_available(), "version": VERSION})
            if p == "/api/diagnostics": return self._json(self._diag())
            if p == "/api/prefs": return self._json(get_prefs())
            if p == "/api/models": return self._json({"models": list_models(), "engine": engine_models(), "active": get_prefs().get("active_model", "")})
            if p == "/api/models/progress": return self._json(dl_state())
            if p == "/api/models/importprogress": return self._json(dict(_import))
            if p == "/api/notes": return self._json({"notes": rows("SELECT * FROM notes ORDER BY updated DESC")})
            if p == "/api/memory":
                term = (q.get("q") or [""])[0]
                return self._json({"memory": recall(term, 30) if term else rows("SELECT id,fact,source,created FROM memory ORDER BY created DESC LIMIT 200")})
            if p == "/api/reminders": return self._json({"reminders": rows("SELECT * FROM reminders ORDER BY due ASC")})
            if p == "/api/cards": return self._json({"cards": rows("SELECT * FROM cards ORDER BY due ASC")})
            if p == "/api/docs":
                return self._json({"docs": rows("""SELECT d.*, (SELECT COUNT(*) FROM chunks c WHERE c.doc=d.id) AS chunks
                                                  FROM docs d ORDER BY created DESC""")})
            if p == "/api/fetchlog": return self._json({"log": rows("SELECT * FROM fetchlog ORDER BY created DESC LIMIT 100")})
            if p == "/api/recipes": return self._json({"recipes": rows("SELECT * FROM recipes ORDER BY created DESC")})
            if p == "/api/skills": return self._json({"skills": rows("SELECT * FROM skills ORDER BY created DESC")})
            if p == "/api/growth": return self._json({"report": growth_report()})
            if p == "/api/exams":
                out = rows("SELECT * FROM exams ORDER BY created DESC")
                for e in out:
                    try: e["questions"] = json.loads(e["questions"])
                    except Exception: e["questions"] = []
                return self._json({"exams": out})
            if p == "/api/wiki": return self._json({"text": wiki_lookup((q.get("q") or [""])[0])})
            if p == "/api/web":
                text, srcs = web_lookup((q.get("q") or [""])[0]); log_fetch("web", (q.get("q") or [""])[0], text, srcs)
                return self._json({"text": text, "sources": srcs})
            if p == "/api/backup":
                b = self._backup()
                return self._bytes(b, "application/zip")
            if p == "/api/updatecheck": return self._json(update_check())
            if p == "/api/updatedownload": return self._json({"error": "Use POST for downloads."}, 405)
            if p == "/api/setup": return self._json(setup_state())
            return self._static(p)
        except Exception as e:
            return self._json({"error": str(e), "trace": traceback.format_exc()[-600:]}, 500)

    # -------- POST
    def do_POST(self):
        if not self._local_request(): return self._json({"error": "Local requests only."}, 403)
        _touch()
        _u = urllib.parse.urlparse(self.path); p = _u.path
        if p == "/api/models/import":
            return self._import_model(urllib.parse.parse_qs(_u.query))
        try:
            body = self._read()
            if p == "/api/updatedownload": return self._json(update_download())
            if p == "/api/prefs": return self._json(set_prefs(body))
            if p == "/api/chat": return self._chat(body)
            if p == "/api/summarize":
                txt = body.get("text", "")[:12000]
                out = llm_once([{"role": "user", "content":
                    "Summarise the following conversation in a few tight paragraphs, keeping key facts, "
                    "decisions and any to-dos:\n\n" + txt}], 700)
                return self._json({"summary": out})
            if p == "/api/calc": return self._json({"result": calculator(body.get("expr", ""))})
            if p == "/api/notes":
                if body.get("delete"): run("DELETE FROM notes WHERE id=?", (body["delete"],)); return self._json({"ok": True})
                now = time.time(); nid = body.get("id")
                if nid: run("UPDATE notes SET title=?, body=?, updated=? WHERE id=?", (body.get("title",""), body.get("body",""), now, nid))
                else:
                    nid = run("INSERT INTO notes(title,body,created,updated) VALUES(?,?,?,?)", (body.get("title",""), body.get("body",""), now, now))
                    for f in re.split(r"[.\n]", body.get("body", "")):
                        if 25 < len(f.strip()) < 200: remember(f.strip(), "note")
                return self._json({"ok": True, "id": nid})
            if p == "/api/memory":
                if body.get("delete"):
                    run("DELETE FROM memory WHERE id=?", (body["delete"],)); run("DELETE FROM memory_fts WHERE rowid=?", (body["delete"],))
                    return self._json({"ok": True})
                return self._json({"ok": bool(remember(body.get("fact",""), body.get("source","manual")))})
            if p == "/api/reminders":
                if body.get("delete"): run("DELETE FROM reminders WHERE id=?", (body["delete"],)); return self._json({"ok": True})
                if body.get("done") is not None:
                    run("UPDATE reminders SET done=? WHERE id=?", (1 if body["done"] else 0, body["id"])); return self._json({"ok": True})
                return self._json({"ok": True, "id": run("INSERT INTO reminders(text,due,done) VALUES(?,?,0)",
                                                          (body.get("text",""), float(body.get("due") or 0)))})
            if p == "/api/cards":
                if body.get("delete"): run("DELETE FROM cards WHERE id=?", (body["delete"],)); return self._json({"ok": True})
                if body.get("review") is not None:
                    c = one("SELECT * FROM cards WHERE id=?", (body["id"],))
                    if not c: return self._json({"ok": False})
                    iv = c["interval"] or 0
                    iv = 1 if not body["review"] else (2 if iv < 2 else min(30, iv * 2))
                    run("UPDATE cards SET interval=?, due=?, reps=reps+1 WHERE id=?",
                        (iv, time.time() + iv * 86400, c["id"]))
                    return self._json({"ok": True, "interval": iv})
                return self._json({"ok": True, "id": run("INSERT INTO cards(q,a,interval,due,reps,created) VALUES(?,?,0,?,0,?)",
                                                          (body.get("q",""), body.get("a",""), time.time(), time.time()))})
            if p == "/api/makecards":
                text = body.get("text", "")[:8000]; n = int(body.get("n") or 5)
                try:
                    arr = llm_json("Make %d flashcards from this text. Return ONLY a JSON array of "
                                   '{"q":"...","a":"..."}. Keep answers short.\n\n' % n + text, 1400)
                except Exception:
                    return self._json({"cards": []})
                made = []
                for it in arr if isinstance(arr, list) else []:
                    if isinstance(it, dict) and it.get("q") and it.get("a"):
                        run("INSERT INTO cards(q,a,interval,due,reps,created) VALUES(?,?,0,?,0,?)",
                            (it["q"], it["a"], time.time(), time.time())); made.append(it)
                return self._json({"cards": made})
            if p == "/api/docs/add":
                name = body.get("name") or "document"
                raw = body.get("data")
                if raw:
                    try: b = base64.b64decode(raw.split(",")[-1], validate=True)
                    except Exception: return self._json({"error": "The uploaded document is not valid base64 data."}, 400)
                    if len(b) > MAX_JSON_BODY: return self._json({"error": "Document is too large (32 MB maximum)."}, 413)
                    if name.lower().endswith(".pdf") or b[:4] == b"%PDF":
                        txt = pdf_text(b)
                        if not txt: return self._json({"error": "Could not read text from that PDF. It may be scanned or protected."}, 400)
                        return self._json(ingest(name, txt, "pdf"))
                    text = b.decode("utf-8", "ignore")
                    if not text.strip(): return self._json({"error": "The document is empty or is not a supported text file."}, 400)
                    return self._json(ingest(name, text, "text"))
                text = body.get("text", "")
                if not str(text).strip(): return self._json({"error": "There is no text to add."}, 400)
                return self._json(ingest(name, text, "text"))
            if p == "/api/docs/delete":
                did = body.get("id")
                for c in rows("SELECT id FROM chunks WHERE doc=?", (did,)):
                    run("DELETE FROM chunks_fts WHERE rowid=?", (c["id"],))
                run("DELETE FROM chunks WHERE doc=?", (did,)); run("DELETE FROM docs WHERE id=?", (did,))
                return self._json({"ok": True})
            if p == "/api/skills":
                if body.get("delete"): run("DELETE FROM skills WHERE id=?", (body["delete"],)); return self._json({"ok": True})
                return self._json({"ok": True})
            if p == "/api/recipes":
                if body.get("delete"): run("DELETE FROM recipes WHERE id=?", (body["delete"],)); return self._json({"ok": True})
                return self._json({"ok": True, "id": run("INSERT INTO recipes(name,prompt,created) VALUES(?,?,?)",
                                                          (body.get("name",""), body.get("prompt",""), time.time()))})
            if p == "/api/exams":
                if body.get("delete"): run("DELETE FROM exams WHERE id=?", (body["delete"],)); return self._json({"ok": True})
                return self._json({"ok": True, "id": run("INSERT INTO exams(title,questions,created) VALUES(?,?,?)",
                                                          (body.get("title","Quiz"), json.dumps(body.get("questions",[])), time.time()))})
            if p == "/api/quiz": return self._json({"questions": make_quiz(body.get("topic",""), int(body.get("n") or 5))})
            if p == "/api/models/download": return self._json(start_download(body.get("url", ""), body.get("name", "")))
            if p == "/api/models/active":
                name = safe_model_name(body.get("name", ""))
                if not name or not os.path.isfile(os.path.join(MODELS, name)):
                    return self._json({"ok": False, "error": "That model is not installed."}, 400)
                set_prefs({"active_model": name})
                with open(os.path.join(DATA, "active_model.txt"), "w", encoding="utf-8") as f:
                    f.write(name)
                stopped = stop_engine()
                started = start_engine()
                return self._json({"ok": bool(stopped and started), "active": name,
                                   "error": _setup.get("error", "")})
            if p == "/api/quit": return self._json({"ok": quit_app()})
            if p == "/api/setup/download": return self._json({"ok": download_model(body.get("which", "0.6b"))})
            if p == "/api/setup/engine": return self._json({"ok": start_engine()})
            if p == "/api/engine/restart":
                stop_engine()
                time.sleep(0.5)
                _engine_try["last"] = 0.0
                return self._json({"ok": start_engine(), "error": _setup.get("error", "")})
            if p == "/api/restore":
                try: b = base64.b64decode((body.get("data") or "").split(",")[-1], validate=True)
                except Exception: return self._json({"ok": False, "error": "The backup file is not valid base64 data."}, 400)
                return self._json(self._restore(b))
            return self._json({"error": "not found"}, 404)
        except Exception as e:
            return self._json({"error": str(e), "trace": traceback.format_exc()[-600:]}, 500)

    # -------- chat
    def _chat(self, body):
        prefs = get_prefs()
        history = body.get("history") or []
        msg = (body.get("message") or "").strip()
        has_docs = bool(one("SELECT id FROM docs LIMIT 1"))
        kind = plan(msg, has_docs)
        mem = recall(msg, 5)
        context, srcs, doc_hits = "", [], None
        if kind == "web":
            context, srcs = web_lookup(msg)
            log_fetch("web", msg, context, srcs)
            if not context: kind = "web-none"
        elif kind == "wiki":
            context = wiki_lookup(msg)
            log_fetch("wiki", msg, context, [])
            if context: srcs = [{"title": "Wikipedia", "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(msg)}]
            else: kind = "none"
        elif kind == "docs":
            doc_hits = doc_search(msg, 6)
            if not doc_hits: kind = "docs-none"
        elif kind == "memory":
            if mem: context = "User's saved notes/memory:\n" + "\n".join("- " + m["fact"] for m in mem)
        elif kind == "calc":
            res = calculator((CALC_RE.search(msg).group(1) if CALC_RE.search(msg) else msg))
            context = "Calculator: " + res if res else ""
            kind = "calc" if res else "none"
        sk = skills_for(msg)
        msgs = build_messages(history, msg, "web" if kind.startswith("web") else "wiki", context, mem, prefs, doc_hits,
                              sk[0] if sk else None)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store"); self.send_header("Connection", "close")
        self.end_headers()
        def send(ev, obj):
            self.wfile.write(("event: %s\ndata: %s\n\n" % (ev, json.dumps(obj))).encode()); self.wfile.flush()
        send("meta", {"tool": kind, "sources": srcs, "memory": len(mem),
                      "docs": len(doc_hits or []), "mode": prefs.get("mode"),
                      "skill": sk[0]["name"] if sk else ""})
        acc = []
        try:
            for t in llm_stream(msgs):
                acc.append(t)
                send("tok", {"t": t})
        except Exception as e:
            send("err", {"error": str(e)})
        send("done", {"tool": kind})
        self.close_connection = True
        # v9.31.1: the same good turn may become a skill NOVA writes for itself
        try:
            threading.Thread(target=forge_skill, args=(msg, "".join(acc)), daemon=True).start()
        except Exception:
            pass

    def _import_model(self, q):
        name = safe_model_name((q.get("name") or ["model.gguf"])[0])
        if not name:
            return self._json({"ok": False, "error": "Choose a valid .gguf model file."}, 400)
        if _import.get("active"):
            return self._json({"ok": False, "error": "Another model import is already running."}, 409)
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_MODEL_BYTES:
            return self._json({"ok": False, "error": "The model upload has an invalid size (maximum 64 GB)."}, 400)
        tmp = os.path.join(MODELS, name + ".%d.part" % os.getpid())
        _import.update(active=True, name=name, done=0, total=n, error="")
        try:
            first = b""
            left = n
            with open(tmp, "wb") as f:
                while left > 0:
                    chunk = self.rfile.read(min(1024 * 1024, left))
                    if not chunk: raise IOError("Upload ended before the complete model was received.")
                    if len(first) < 4: first += chunk[:4-len(first)]
                    f.write(chunk)
                    left -= len(chunk)
                    _import["done"] = n - left
                f.flush(); os.fsync(f.fileno())
            if first != b"GGUF": raise ValueError("This file does not have a valid GGUF header.")
            if os.path.getsize(tmp) <= 1_000_000: raise ValueError("The model file is too small to be valid.")
            dest = os.path.join(MODELS, name)
            if os.path.exists(dest):
                if os.path.getsize(dest) == n and filecmp.cmp(tmp, dest, shallow=False):
                    os.remove(tmp)
                    _import.update(active=False, done=n)
                    return self._json({"ok": True, "name": name, "already_exists": True})
                stem, ext = os.path.splitext(name); idx = 2
                while os.path.exists(os.path.join(MODELS, "%s-%d%s" % (stem, idx, ext))): idx += 1
                name = "%s-%d%s" % (stem, idx, ext)
                dest = os.path.join(MODELS, name)
            os.replace(tmp, dest)
            _import.update(active=False, done=n, name=name)
            return self._json({"ok": True, "name": name})
        except Exception as e:
            try:
                if os.path.exists(tmp): os.remove(tmp)
            except Exception: pass
            _import.update(active=False, error=str(e))
            return self._json({"ok": False, "error": str(e)}, 400)

    # -------- misc
    def _diag(self):
        engine = False; emodel = ""
        try:
            j = json.loads(http_get(LLAMA + "/v1/models", timeout=5)); engine = True
            emodel = (j.get("data") or [{}])[0].get("id", "")
        except Exception: pass
        cnt = {t: (one("SELECT COUNT(*) c FROM " + t) or {}).get("c", 0)
               for t in ("notes", "memory", "docs", "chunks", "cards", "reminders", "fetchlog")}
        return {"version": VERSION, "engine": engine, "model": emodel,
                "embed": embed_available(), "pdf": HAVE_PDF,
                "llama_url": LLAMA, "embed_url": EMBED, "port": PORT,
                "data_dir": DATA, "root": ROOT, "counts": cnt}

    def _backup(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for fn in ("nova.db", "prefs.json"):
                fp = os.path.join(DATA, fn)
                if os.path.isfile(fp): z.write(fp, fn)
        return buf.getvalue()

    def _restore(self, b):
        staged = []
        try:
            if not b or len(b) > MAX_BACKUP_BYTES:
                return {"ok": False, "error": "Backup is empty or larger than 100 MB."}
            with zipfile.ZipFile(io.BytesIO(b)) as z:
                files = {i.filename: i for i in z.infolist() if not i.is_dir()}
                allowed = {"nova.db", "prefs.json"}
                if not set(files).issubset(allowed) or not files:
                    return {"ok": False, "error": "This is not a NOVA backup archive."}
                payload = {}
                for name, info in files.items():
                    if info.file_size > MAX_BACKUP_BYTES:
                        return {"ok": False, "error": "A backup entry is too large."}
                    payload[name] = z.read(info)
            if "nova.db" in payload:
                fd, tmpdb = tempfile.mkstemp(prefix="nova-restore-", suffix=".db", dir=DATA)
                os.close(fd)
                with open(tmpdb, "wb") as f: f.write(payload["nova.db"])
                test = sqlite3.connect(tmpdb, timeout=10)
                try:
                    integrity = test.execute("PRAGMA integrity_check").fetchone()[0]
                    tables = {r[0] for r in test.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if integrity != "ok" or not {"notes", "memory", "docs", "chunks", "cards", "reminders"}.issubset(tables):
                        raise ValueError("The backup database is incomplete or damaged.")
                finally: test.close()
                staged.append((tmpdb, DB))
            if "prefs.json" in payload:
                prefs = json.loads(payload["prefs.json"].decode("utf-8"))
                if not isinstance(prefs, dict): raise ValueError("The backup settings file is invalid.")
                fd, tmpprefs = tempfile.mkstemp(prefix="nova-prefs-", suffix=".json", dir=DATA)
                os.close(fd)
                with open(tmpprefs, "w", encoding="utf-8") as f:
                    json.dump(prefs, f, ensure_ascii=False, indent=1)
                staged.append((tmpprefs, PREFS))
            for src, dest in staged: os.replace(src, dest)
            init_db()
            return {"ok": True}
        except Exception as e:
            for src, _ in staged:
                try:
                    if os.path.exists(src): os.remove(src)
                except Exception: pass
            return {"ok": False, "error": str(e)}

    def _static(self, p):
        if p in ("/", ""): p = "/index.html"
        base = os.path.realpath(WEB)
        fn = os.path.realpath(os.path.join(base, p.lstrip("/\\")))
        try: inside = os.path.commonpath([base, fn]) == base
        except ValueError: inside = False
        if not inside or not os.path.isfile(fn): self.send_error(404); return
        with open(fn, "rb") as f: b = f.read()
        self._bytes(b, mimetypes.guess_type(fn)[0] or "application/octet-stream")

# ---------------------------------------------------------------- models
def list_models():
    out = []
    if os.path.isdir(MODELS):
        for f in sorted(os.listdir(MODELS)):
            fp = os.path.join(MODELS, f)
            if f.lower().endswith(".gguf") and os.path.isfile(fp) and model_ok(fp):
                out.append({"name": f, "size": os.path.getsize(fp)})
    return out

def engine_models():
    try: return [m.get("id") for m in json.loads(http_get(LLAMA + "/v1/models", timeout=5)).get("data", [])]
    except Exception: return []

_dl = {"name": "", "done": 0, "total": 0, "state": "idle", "error": ""}
def dl_state(): return dict(_dl)

def safe_model_name(value):
    value = str(value or "").replace("\\", "/").split("/")[-1]
    value = re.sub(r"[^A-Za-z0-9._-]", "_", value).strip("._")
    if not value: return ""
    if not value.lower().endswith(".gguf"): value += ".gguf"
    if len(value) > 180: return ""
    return value

def valid_model_download_url(url):
    try:
        u = urllib.parse.urlsplit(url)
        return (u.scheme == "https" and u.hostname and u.hostname.lower() in
                ("huggingface.co", "www.huggingface.co", "hf.co") and not u.username and not u.password
                and u.port in (None, 443))
    except Exception:
        return False

def start_download(url, name):
    name = safe_model_name(name)
    if _dl["state"] == "running": return {"ok": False, "error": "A model download is already running."}
    if not name or not valid_model_download_url(url):
        return {"ok": False, "error": "Use a direct HTTPS model URL from huggingface.co or hf.co and a .gguf filename."}
    tmp = os.path.join(MODELS, name + ".part")
    def work():
        _dl.update(name=name, done=0, total=0, state="running", error="")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                if total > MAX_MODEL_BYTES: raise ValueError("Model exceeds the 64 GB limit.")
                _dl["total"] = total
                while True:
                    b = r.read(262144)
                    if not b: break
                    _dl["done"] += len(b)
                    if _dl["done"] > MAX_MODEL_BYTES: raise ValueError("Model exceeds the 64 GB limit.")
                    f.write(b)
                f.flush(); os.fsync(f.fileno())
            with open(tmp, "rb") as f:
                if f.read(4) != b"GGUF": raise ValueError("The downloaded file is not a valid GGUF model.")
            if os.path.getsize(tmp) <= 1_000_000: raise ValueError("The downloaded model file is incomplete.")
            dest = os.path.join(MODELS, name)
            if os.path.exists(dest):
                stem, ext = os.path.splitext(name); idx = 2
                while os.path.exists(os.path.join(MODELS, "%s-%d%s" % (stem, idx, ext))): idx += 1
                dest = os.path.join(MODELS, "%s-%d%s" % (stem, idx, ext))
                name = os.path.basename(dest)
            os.replace(tmp, dest)
            _dl.update(name=name, state="done", error="")
        except Exception as e:
            try:
                if os.path.exists(tmp): os.remove(tmp)
            except Exception: pass
            _dl.update(state="error", error=str(e))
    threading.Thread(target=work, daemon=True).start()
    return {"ok": True, "name": name}


# ---------------------------------------------------------------- skills (self-built)
STOPW = set("the a an is are was were of to in on for and or with my me i you your it this that please do does did can could should would".split())

def _toks(t):
    return {w for w in re.findall(r"[a-z0-9]{3,}", (t or "").lower()) if w not in STOPW}

def skills_for(q, limit=1):
    """The best self-written skill for this question, or none."""
    try:
        qs = _toks(q)
        if not qs:
            return []
        best, score = None, 0
        for r in rows("SELECT * FROM skills"):
            trig = _toks(r["trigger"])
            if not trig:
                continue
            shared = len(qs & trig)
            ov = shared / max(1, len(trig))
            if shared >= 2 and ov >= 0.4 and ov > score:
                best, score = r, ov
        if best:
            run("UPDATE skills SET uses=uses+1 WHERE id=?", (best["id"],))
            return [best]
    except Exception:
        pass
    return []

FORGE_PROMPT = (
    "A request just went well. Turn it into a REUSABLE skill so NOVA handles this KIND of "
    "request well in future.\nReply with EXACTLY three lines and nothing else:\n"
    "name=<2 to 4 words>\ntrigger=<5 to 12 plain keywords that describe this KIND of request>\n"
    "instruction=<what NOVA should do, as a general rule, with {q} where the user's text goes>\n"
    "The trigger must describe the KIND of request, not this exact sentence, and must not name "
    "this specific topic. No markdown.\n\nRequest: ")

def parse_skill(reply):
    name = trig = ins = None
    for raw in (reply or "").split("\n"):
        line = raw.strip().removeprefix("```").strip()
        if line.startswith("name=") and name is None: name = line[5:].strip()
        elif line.startswith("trigger=") and trig is None: trig = line[8:].strip()
        elif line.startswith("instruction=") and ins is None: ins = line[12:].replace("\\n", "\n").strip()
    if not name or not trig or not ins: return None
    if len(name) > 40 or not (25 <= len(ins) <= 600): return None
    if len(_toks(trig)) < 3: return None
    if "{q}" not in ins and len(ins) < 60: return None
    return (name, trig, ins)

def forge_skill(question, answer):
    """After a good, repeatable turn, ask the model to generalise it into a skill."""
    if not question or not answer or len(question) < 12 or len(question) > 300 or len(answer) < 60:
        return
    if re.match(r"(?i)^\s*(hi|hey|hello|thanks|ok|okay|hmm|bye)\b", question):
        return
    if not re.search(r"(?i)\b(summaris|summariz|explain|translate|make (?:me )?(?:notes|a list|a table|a plan)|"
                     r"write (?:me )?(?:an? )?(?:essay|email|letter|paragraph|story|report)|compare|list the|"
                     r"step by step|how (?:do|to)|convert|solve|samjha|banao|likh)\b", question):
        return
    if skills_for(question):
        return
    if (one("SELECT COUNT(*) c FROM skills") or {}).get("c", 0) >= 20:
        return
    try:
        out = llm_once([{"role": "user", "content": FORGE_PROMPT + question + "\nAnswer NOVA gave: " + answer[:400]}], 220)
        sk = parse_skill(out)
        if not sk:
            return
        for r in rows("SELECT trigger FROM skills"):
            if _toks(r["trigger"]) == _toks(sk[1]):
                return
        run("INSERT INTO skills(name, trigger, instruction, source, created) VALUES(?,?,?,?,?)",
            (sk[0], sk[1], sk[2], "nova", time.time()))
    except Exception:
        pass

def growth_report():
    sk = rows("SELECT * FROM skills ORDER BY created DESC")
    cnt = {t: (one("SELECT COUNT(*) c FROM " + t) or {}).get("c", 0)
           for t in ("notes", "memory", "docs", "chunks", "cards", "reminders", "fetchlog", "skills")}
    out = ["GROWTH REPORT - " + time.strftime("%d %b, %H:%M")]
    out.append("skills I have written myself: %d" % cnt["skills"])
    for r in sk[:12]:
        out.append("  - %s  (used %dx)" % (r["name"], r["uses"] or 0))
    out.append("memory facts: %d   notes: %d   documents: %d (%d chunks)   cards: %d   reminders: %d"
               % (cnt["memory"], cnt["notes"], cnt["docs"], cnt["chunks"], cnt["cards"], cnt["reminders"]))
    out.append("lookups logged: %d" % cnt["fetchlog"])
    return "\n".join(out)

# ---------------------------------------------------------------- engine control
_proc = {"engine": None, "embed": None}
_setup = {"downloading": False, "done": 0, "total": 0, "name": "", "error": "", "phase": ""}
_import = {"active": False, "name": "", "done": 0, "total": 0, "error": ""}
MODEL_URLS = {
    "1.7b": ("Qwen3-1.7B-Q4_K_M.gguf", "https://huggingface.co/unsloth/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q4_K_M.gguf"),
    "0.6b": ("Qwen3-0.6B-Q4_K_M.gguf", "https://huggingface.co/unsloth/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q4_K_M.gguf"),
}

def find_model():
    chosen = ""
    try:
        with open(os.path.join(DATA, "active_model.txt"), encoding="utf-8") as f:
            chosen = safe_model_name(f.read().strip())
    except Exception:
        pass
    if chosen and os.path.isfile(os.path.join(MODELS, chosen)):
        return os.path.join(MODELS, chosen)
    gg = [f for f in sorted(os.listdir(MODELS)) if f.lower().endswith(".gguf")] if os.path.isdir(MODELS) else []
    return os.path.join(MODELS, gg[0]) if gg else ""

def engine_alive():
    try:
        http_get(LLAMA + "/health", timeout=3); return True
    except Exception:
        return False

def _spawn(args, log):
    flags = 0x08000000 if os.name == "nt" else 0
    os.makedirs(os.path.dirname(log), exist_ok=True)
    with open(log, "w", encoding="utf-8", errors="replace") as out:
        return subprocess.Popen(args, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT,
                                creationflags=flags)

def model_ok(path):
    """A real, complete model file - not a .part, not a stub."""
    try:
        return bool(path) and os.path.isfile(path) and os.path.getsize(path) > 1_000_000
    except Exception:
        return False

def engine_log_tail(n=14):
    try:
        with open(os.path.join(DATA, "engine.log"), encoding="utf-8", errors="ignore") as f:
            return "\n".join(f.read().splitlines()[-n:])
    except Exception:
        return ""

_running_model = {"path": "", "started": 0.0}

def stop_engine():
    """Stop only llama-server processes launched by this NOVA instance."""
    ok = True
    for key in ("embed", "engine"):
        proc = _proc.get(key)
        if proc is None: continue
        try:
            if proc.poll() is None:
                proc.terminate()
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait(timeout=3)
        except Exception:
            ok = False
        _proc[key] = None
    _running_model["path"] = ""
    _running_model["started"] = 0.0
    _embed_ok.update(v=None, checked=0.0)
    return ok

def start_engine():
    m = find_model()
    if not m:
        _setup["error"] = "No model file in the models folder. Download one or import a .gguf model."
        return False
    if not model_ok(m):
        _setup["error"] = ("The model file looks incomplete (%s). Delete it and download again."
                           % os.path.basename(m))
        return False
    desired = os.path.realpath(m)
    proc = _proc.get("engine")
    if proc is not None and proc.poll() is not None:
        stop_engine()  # also stop a still-running embeddings child
        proc = None
    if proc is not None and proc.poll() is None:
        if _running_model.get("path") != desired:
            stop_engine()
        else:
            if engine_alive():
                _setup["error"] = ""
            elif time.time() - _running_model.get("started", 0) < 120:
                _setup["error"] = "The model engine is still starting."
            else:
                _setup["error"] = "The model engine did not become ready; check engine.log."
                stop_engine()
                return False
            return True
    if engine_alive():
        _setup["error"] = "Port 8080 is already being used by another llama-server. Close it or change its port."
        return False
    exe = os.path.join(ROOT, "llama-server.exe")
    if not os.path.isfile(exe):
        _setup["error"] = "llama-server.exe is missing from the NOVA folder (antivirus may have removed it)."
        return False
    try:
        _proc["engine"] = _spawn([exe, "-m", m, "--alias", "NOVA", "-c", "4096",
                                  "--port", "8080", "--host", "127.0.0.1"],
                                 os.path.join(DATA, "engine.log"))
        _running_model["path"] = desired
        _running_model["started"] = time.time()
        ed = os.path.join(MODELS, "embed")
        ef = [f for f in sorted(os.listdir(ed)) if f.lower().endswith(".gguf") and model_ok(os.path.join(ed, f))] if os.path.isdir(ed) else []
        if ef:
            _proc["embed"] = _spawn([exe, "-m", os.path.join(ed, ef[0]), "--embeddings",
                                     "--pooling", "mean", "-c", "512", "--port", "8081",
                                     "--host", "127.0.0.1"], os.path.join(DATA, "embed.log"))
        _embed_ok.update(v=None, checked=0.0)
        _setup["error"] = ""
        return True
    except Exception as e:
        _setup["error"] = str(e)
        stop_engine()
        return False

def download_model(which):
    if _setup["downloading"]: return False
    name, url = MODEL_URLS.get(which, MODEL_URLS["0.6b"])
    def work():
        _setup.update(downloading=True, done=0, total=0, name=name, error="", phase="downloading")
        tmp = os.path.join(MODELS, name + ".part")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                _setup["total"] = int(r.headers.get("Content-Length") or 0)
                if _setup["total"] > MAX_MODEL_BYTES: raise ValueError("Model exceeds the 64 GB limit.")
                while True:
                    b = r.read(262144)
                    if not b: break
                    f.write(b); _setup["done"] += len(b)
                    if _setup["done"] > MAX_MODEL_BYTES: raise ValueError("Model exceeds the 64 GB limit.")
                f.flush(); os.fsync(f.fileno())
            with open(tmp, "rb") as f:
                if f.read(4) != b"GGUF": raise ValueError("The downloaded file is not a valid GGUF model.")
            if os.path.getsize(tmp) <= 1_000_000: raise ValueError("The downloaded model file is incomplete.")
            dest = os.path.join(MODELS, name)
            if os.path.exists(dest) and filecmp.cmp(tmp, dest, shallow=False):
                os.remove(tmp)
            elif os.path.exists(dest):
                stem, ext = os.path.splitext(name); idx = 2
                while os.path.exists(os.path.join(MODELS, "%s-%d%s" % (stem, idx, ext))): idx += 1
                name = "%s-%d%s" % (stem, idx, ext)
                os.replace(tmp, os.path.join(MODELS, name))
            else:
                os.replace(tmp, dest)
            with open(os.path.join(DATA, "active_model.txt"), "w", encoding="utf-8") as f: f.write(name)
            set_prefs({"active_model": name})
            stop_engine()
            _setup["phase"] = "starting"
            if not start_engine(): raise RuntimeError(_setup.get("error") or "The model engine could not be started.")
            _setup.update(downloading=False, phase="ready", error="")
        except Exception as e:
            try:
                if os.path.exists(tmp): os.remove(tmp)
            except Exception: pass
            _setup.update(downloading=False, phase="error", error=str(e))
    threading.Thread(target=work, daemon=True).start()
    return True

_engine_try = {"last": 0.0, "tries": 0}

def engine_watchdog():
    """Keep trying to bring the engine up; never leave the app hanging silently."""
    while True:
        time.sleep(15)
        try:
            if engine_alive():
                _engine_try["tries"] = 0
                continue
            if not find_model() or not model_ok(find_model()):
                continue
            if time.time() - _engine_try["last"] < 20:
                continue
            _engine_try["last"] = time.time()
            _engine_try["tries"] += 1
            start_engine()
        except Exception:
            pass

def setup_state():
    m = find_model()
    alive = engine_alive()
    return {"model": os.path.basename(m) if m else "", "engine": alive,
            "needs_setup": not bool(m), "download": dict(_setup),
            "embed": embed_available(), "models": list_models(),
            "model_ok": model_ok(m), "engine_error": _setup.get("error", ""),
            "engine_log": "" if alive else engine_log_tail()}

_last = {"t": time.time()}

def _touch():
    _last["t"] = time.time()

def watchdog():
    """Quit on its own once the NOVA window has been closed for a while."""
    while True:
        time.sleep(20)
        if time.time() - _last["t"] > 300:
            quit_app()
            return

def open_window():
    url = "http://127.0.0.1:%d" % PORT
    cands = [
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", ""), r"Google\Chrome\Application\chrome.exe"),
        os.path.join(os.environ.get("LocalAppData", ""), r"Google\Chrome\Application\chrome.exe"),
    ]
    for exe in cands:
        if exe and os.path.isfile(exe):
            try:
                subprocess.Popen([exe, "--app=" + url, "--window-size=1240,860"])
                return True
            except Exception:
                pass
    try:
        os.startfile(url)
        return True
    except Exception:
        return False

def quit_app():
    stop_engine()
    threading.Timer(0.7, lambda: os._exit(0)).start()
    return True

# ---------------------------------------------------------------- quiz / update
def make_quiz(topic, n=5):
    topic = (topic or "").strip()
    if not topic: return []
    try:
        arr = llm_json("Create %d multiple-choice questions to test understanding of: %s\n"
                       'Return ONLY a JSON array. Each item: {"q":"...","options":["a","b","c","d"],"answer":0}\n'
                       "answer is the 0-based index of the correct option. No prose, no markdown." % (n, topic), 1400)
        qs = []
        for it in arr if isinstance(arr, list) else []:
            if isinstance(it, dict) and it.get("q") and it.get("options"):
                qs.append({"q": it["q"], "options": it["options"], "answer": int(it.get("answer", 0))})
        return qs
    except Exception:
        return []

def update_check():
    """Look up the newest desktop build on the public releases page."""
    try:
        j = json.loads(http_get("https://api.github.com/repos/rautshivamxyz-beep/NOVA-desk/releases", timeout=15,
                                headers={"Accept": "application/vnd.github+json"}))
        for r in j:
            if "desktop" in (r.get("tag_name") or "").lower():
                zip_url = ""
                for a in r.get("assets", []):
                    if (a.get("name") or "").lower().endswith(".zip"):
                        zip_url = a.get("browser_download_url") or ""
                        break
                return {"latest": r.get("tag_name"), "url": r.get("html_url"), "zip": zip_url,
                        "published": (r.get("published_at") or "")[:10],
                        "notes": (r.get("body") or "")[:300], "current": VERSION}
    except Exception as e:
        return {"error": str(e), "current": VERSION}
    return {"current": VERSION}

def update_download():
    """Fetch the latest desktop zip into the user's Downloads folder."""
    u = update_check()
    if not u.get("zip"):
        return {"ok": False, "error": u.get("error") or "No desktop build found on the releases page.", "zip": ""}
    try:
        dest_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        if not os.path.isdir(dest_dir):
            dest_dir = os.path.expanduser("~")
        dest = os.path.join(dest_dir, "NOVA-Desktop-Windows-NEW.zip")
        req = urllib.request.Request(u["zip"], headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as f:
            while True:
                b = r.read(262144)
                if not b:
                    break
                f.write(b)
        return {"ok": True, "path": dest, "tag": u.get("latest", ""), "size": os.path.getsize(dest), "zip": u.get("zip", "")}
    except Exception as e:
        return {"ok": False, "error": str(e), "zip": u.get("zip", "")}

# ---------------------------------------------------------------- main
def main():
    init_db()
    if os.environ.get("NOVA_DEBUG") != "1":
        try:
            sys.stdout = sys.stderr = open(os.path.join(DATA, "backend.log"), "a", buffering=1)
        except Exception:
            pass
    try:
        start_engine()
    except Exception:
        pass
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        # Reuse only an already-running NOVA instance; never open an unrelated
        # service merely because it happens to occupy our preferred port.
        try:
            info = json.loads(http_get("http://127.0.0.1:%d/api/health" % PORT, timeout=2))
            if info.get("version"):
                open_window()
                return
        except Exception:
            pass
        print("NOVA could not start: port %d is already in use." % PORT, flush=True)
        return
    srv.daemon_threads = True
    try:
        with open(os.path.join(DATA, "backend.pid"), "w", encoding="ascii") as f: f.write(str(os.getpid()))
    except Exception: pass
    if os.environ.get("NOVA_NO_OPEN") != "1":
        threading.Timer(1.2, open_window).start()
    threading.Thread(target=watchdog, daemon=True).start()
    threading.Thread(target=engine_watchdog, daemon=True).start()
    print("NOVA backend %s on http://127.0.0.1:%d" % (VERSION, PORT), flush=True)
    srv.serve_forever()

if __name__ == "__main__":
    main()
