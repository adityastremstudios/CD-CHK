"""Unique number dispenser: har number sirf ek baar niklega (Flask + Postgres).

Environment variables:
  DATABASE_URL  Postgres connection string (Neon / Supabase / Render Postgres)
  ADMIN_PASS    admin password (zaroori)
  ADMIN_USER    admin username (default: admin)
  DONE_MSG      sab numbers khatam hone par dikhne wala message (optional)
"""
import os
import secrets
from contextlib import contextmanager
from functools import wraps

import psycopg2
from flask import Flask, Response, jsonify, redirect, render_template_string, request
from psycopg2.extras import execute_values

DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS")
DONE_MSG = os.environ.get("DONE_MSG", "Sab numbers use ho gaye. Update jald aayega.")

app = Flask(__name__)
app.config["MAX_FORM_MEMORY_SIZE"] = 50_000_000  # badi list paste karne ke liye
app.config["MAX_CONTENT_LENGTH"] = 20_000_000  # ek upload me total 20 MB tak


@contextmanager
def cursor():
    """Ek connection + transaction: success par commit, error par rollback."""
    con = psycopg2.connect(DATABASE_URL, connect_timeout=10)
    try:
        with con, con.cursor() as c:
            yield c
    finally:
        con.close()


def init_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable set karo")
    with cursor() as c:
        c.execute("SELECT pg_advisory_xact_lock(42)")  # multiple workers ek saath start hon to race na ho
        c.execute(
            """CREATE TABLE IF NOT EXISTS numbers(
                id BIGSERIAL PRIMARY KEY,
                value TEXT NOT NULL UNIQUE,
                used BOOLEAN NOT NULL DEFAULT FALSE,
                used_at TIMESTAMPTZ)"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS numbers_unused_idx ON numbers(id) WHERE NOT used")


def read_text(f):
    """Uploaded file ko text me badlo (UTF-8 ya Notepad ka UTF-16)."""
    raw = f.read()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16", errors="replace")
    else:
        text = raw.decode("utf-8-sig", errors="replace")
    return text.replace("\x00", "")


def submitted_values():
    """Form ke textarea aur uploaded .txt files se numbers (unique, order ke saath)."""
    chunks = [request.form.get("nums", "")]
    chunks += [read_text(f) for f in request.files.getlist("file") if f and f.filename]
    lines = (v.strip() for chunk in chunks for v in chunk.splitlines())
    return list(dict.fromkeys(v for v in lines if v))


def admin_only(f):
    @wraps(f)
    def wrapper(*a, **k):
        if not ADMIN_PASS:
            return Response("ADMIN_PASS environment variable set karo", 503)
        au = request.authorization
        ok = (
            au
            and secrets.compare_digest((au.username or "").encode(), ADMIN_USER.encode())
            and secrets.compare_digest((au.password or "").encode(), ADMIN_PASS.encode())
        )
        if not ok:
            return Response("Login chahiye", 401, {"WWW-Authenticate": 'Basic realm="admin"'})
        return f(*a, **k)

    return wrapper


HOME = """<!doctype html>
<html lang="hi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Number nikalo</title>
<style>
:root{--bg:#eef1f4;--ink:#12202b;--muted:#5b6b78;--accent:#0f766e}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
main{width:min(92vw,30rem);text-align:center;padding:2rem 0}
h1{font-size:1.1rem;font-weight:600;color:var(--muted);margin:0 0 1.5rem}
#out{font-size:clamp(2rem,9vw,3.2rem);font-weight:700;letter-spacing:.02em;font-variant-numeric:tabular-nums;
  min-height:1.3em;word-break:break-all;margin-bottom:1.75rem}
button{font:inherit;font-weight:600;padding:.85rem 1.8rem;border:0;border-radius:.5rem;
  background:var(--accent);color:#fff;cursor:pointer}
button:focus-visible{outline:3px solid var(--ink);outline-offset:3px}
button:disabled{opacity:.45;cursor:default}
#msg{margin:1.25rem 0 0;color:var(--muted);min-height:1.4em}
</style></head><body><main>
<h1>Har number sirf ek baar dikhega</h1>
<div id="out" aria-live="polite">–</div>
<button id="b">Agla number nikalo</button>
<p id="msg"></p>
</main>
<script>
const b=document.getElementById('b'),out=document.getElementById('out'),msg=document.getElementById('msg');
b.onclick=async()=>{
  b.disabled=true;msg.textContent='';
  try{
    const r=await (await fetch('/next',{method:'POST'})).json();
    if(r.value){out.textContent=r.value;b.disabled=false;msg.textContent='Ye number ab dobara nahi aayega, copy kar lo.';}
    else{out.textContent='–';msg.textContent=r.message;}
  }catch(e){msg.textContent='Error aaya, dobara try karo.';b.disabled=false;}
};
</script></body></html>"""

ADMIN = """<!doctype html>
<html lang="hi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin</title>
<style>
:root{--bg:#eef1f4;--ink:#12202b;--muted:#5b6b78;--accent:#0f766e;--danger:#a4262c}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
main{width:min(92vw,36rem);margin:0 auto;padding:2rem 0}
h1{font-size:1.4rem;margin:0 0 .5rem}
.counts{color:var(--muted);margin:0 0 1.5rem}
textarea{width:100%;font:inherit;padding:.7rem;border:1px solid #b8c2cb;border-radius:.4rem;margin-bottom:.75rem}
button{font:inherit;font-weight:600;padding:.7rem 1.4rem;border:0;border-radius:.5rem;background:var(--accent);color:#fff;cursor:pointer}
button.danger{background:var(--danger)}
button:focus-visible{outline:3px solid var(--ink);outline-offset:3px}
.note{color:var(--accent);font-weight:600}
form+form{margin-top:1.5rem}
input[type=file]{display:block;margin:.4rem 0 1rem;max-width:100%}
.hint{color:var(--muted);margin:.25rem 0}
h2{font-size:1.1rem;margin:0 0 .5rem}
</style></head><body><main>
<h1>Numbers manage karo</h1>
<p class="counts">Total {{t}}, use hue {{u}}, bache {{t-u}}</p>
{% if added is not none %}<p class="note">{{added}} naye number add hue, {{dupes or 0}} pehle se the (skip kar diye).</p>{% endif %}
{% if deleted is not none %}<p class="note">{{deleted}} number delete hue.</p>{% endif %}
<form method="post" action="/admin/add" enctype="multipart/form-data">
  <label for="file">.txt file se add karo (ek line me ek number, ek se zyada file bhi chalegi)</label>
  <input id="file" type="file" name="file" accept=".txt,text/plain" multiple>
  <p class="hint">ya seedha yahan paste karo</p>
  <textarea name="nums" rows="8" placeholder="Ek line me ek number"></textarea>
  <button>Numbers add karo</button>
</form>
<form method="post" action="/admin/reset" onsubmit="return confirm('Sab numbers wapas unused ho jayenge aur dobara aa sakte hain. Pakka?')">
  <button class="danger">Sab unused kar do</button>
</form>
<form method="post" action="/admin/delete" enctype="multipart/form-data">
  <h2>Kuch numbers delete karo</h2>
  <label for="dfile">.txt file se (ek line me ek number)</label>
  <input id="dfile" type="file" name="file" accept=".txt,text/plain" multiple>
  <p class="hint">ya seedha yahan paste karo</p>
  <textarea name="nums" rows="5" placeholder="Jo numbers delete karne hain"></textarea>
  <button class="danger" onclick="return confirm('Ye numbers delete ho jayenge. Pakka?')">Ye numbers delete karo</button>
</form>
<form method="post" action="/admin/delete-unused" onsubmit="return confirm('Jo numbers abhi tak nikle nahi wo sab delete ho jayenge. Pakka?')">
  <button class="danger">Bache hue (unused) sab delete karo</button>
</form>
<form method="post" action="/admin/delete-all" onsubmit="return confirm('Poora data delete ho jayega, use ho chuke numbers ka record bhi. Pakka?')">
  <button class="danger">Poora data delete karo</button>
</form>
</main></body></html>"""


@app.get("/")
def home():
    return render_template_string(HOME)


@app.post("/next")
def next_number():
    # Ek hi statement me pick + used mark: do log ek saath dabayein to bhi alag number milega.
    with cursor() as c:
        c.execute(
            """UPDATE numbers SET used = TRUE, used_at = now()
               WHERE id = (SELECT id FROM numbers WHERE NOT used
                           ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED)
               RETURNING value"""
        )
        row = c.fetchone()
    if row is None:
        return jsonify(value=None, message=DONE_MSG)
    return jsonify(value=row[0])


@app.get("/admin")
@admin_only
def admin():
    with cursor() as c:
        c.execute("SELECT COUNT(*), COUNT(*) FILTER (WHERE used) FROM numbers")
        t, u = c.fetchone()
    added = request.args.get("added", type=int)
    dupes = request.args.get("dupes", type=int)
    deleted = request.args.get("deleted", type=int)
    return render_template_string(ADMIN, t=t, u=u, added=added, dupes=dupes, deleted=deleted)


@app.post("/admin/add")
@admin_only
def admin_add():
    values = submitted_values()
    added = 0
    if values:
        with cursor() as c:
            rows = execute_values(
                c,
                "INSERT INTO numbers(value) VALUES %s ON CONFLICT DO NOTHING RETURNING 1",
                [(v,) for v in values],
                page_size=10000,
                fetch=True,
            )
            added = len(rows)
    return redirect(f"/admin?added={added}&dupes={len(values) - added}")


@app.post("/admin/reset")
@admin_only
def admin_reset():
    with cursor() as c:
        c.execute("UPDATE numbers SET used = FALSE, used_at = NULL")
    return redirect("/admin")


@app.post("/admin/delete")
@admin_only
def admin_delete():
    values = submitted_values()
    deleted = 0
    if values:
        with cursor() as c:
            c.execute("DELETE FROM numbers WHERE value = ANY(%s)", (values,))
            deleted = c.rowcount
    return redirect(f"/admin?deleted={deleted}")


@app.post("/admin/delete-unused")
@admin_only
def admin_delete_unused():
    with cursor() as c:
        c.execute("DELETE FROM numbers WHERE NOT used")
        deleted = c.rowcount
    return redirect(f"/admin?deleted={deleted}")


@app.post("/admin/delete-all")
@admin_only
def admin_delete_all():
    with cursor() as c:
        c.execute("SELECT COUNT(*) FROM numbers")
        deleted = c.fetchone()[0]
        c.execute("TRUNCATE numbers RESTART IDENTITY")
    return redirect(f"/admin?deleted={deleted}")


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
