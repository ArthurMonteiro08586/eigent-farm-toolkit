#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Eigent farm dashboard — stdlib only, http://127.0.0.1:8750

Reads local artifacts from EIGENT_HOME (default C:/Users/User/tmp/eigent):
  eigent_bank.jsonl        — farm results / trials
  eigent_api_creds*.json   — extracted API creds (masked in UI)
  eigent_used_gh.txt       — consumed GH pool indices
  farm_cdp.log / farm.log  — farm logs (tail)
  GH_ACCOUNTS json         — pool stats (counts only, no creds shown)

Endpoints:
  GET  /            — HTML panel (auto-refresh 30s)
  GET  /api/status  — JSON: bank, creds(masked), pool, log tail
  GET  /api/probe   — live proxy check (/health/liveliness + /key/info), no spend
"""
import json
import os
import sys
import html
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

HOME = os.environ.get("EIGENT_HOME", r"C:/Users/User/tmp/eigent")
GH_PATH = os.environ.get("GH_ACCOUNTS", r"C:/Users/User/tmp/gh_accounts.json")
PORT = int(os.environ.get("DASH_PORT", "8750"))
AUTH = "Bearer" + " "


def mask(v, keep=4):
    s = str(v or "")
    if len(s) <= keep * 2:
        return "*" * len(s)
    return s[:keep] + "…" + s[-keep:] + f" (len {len(s)})"


def read_bank():
    out = []
    p = os.path.join(HOME, "eigent_bank.jsonl")
    if not os.path.exists(p):
        return out
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        red = {}
        for k, v in d.items():
            if any(s in k.lower() for s in ("login", "email", "card", "pass", "totp", "token", "key", "checkout")):
                red[k] = mask(v) if k != "card_tail" else v
            else:
                red[k] = v
        out.append(red)
    return out


def read_creds():
    res = []
    if not os.path.isdir(HOME):
        return res
    for fn in sorted(os.listdir(HOME)):
        if fn.startswith("eigent_api_creds") and fn.endswith(".json"):
            try:
                d = json.load(open(os.path.join(HOME, fn), encoding="utf-8"))
            except Exception as e:
                res.append({"file": fn, "error": str(e)})
                continue
            ent = {
                "file": fn,
                "email": mask(d.get("email"), 3),
                "user_id": d.get("user_id"),
                "token": mask(d.get("token")),
                "key": mask((d.get("key") or {}).get("value")) if isinstance(d.get("key"), dict) else mask(d.get("key")),
                "api_url": (d.get("key") or {}).get("api_url") if isinstance(d.get("key"), dict) else None,
                "models": len(((d.get("models") or {}).get("models")) or []) if isinstance(d.get("models"), dict) else None,
                "credits": d.get("credits"),
            }
            sub = d.get("subscription") or {}
            if isinstance(sub, dict):
                ent["plan"] = sub.get("plan_key") or sub.get("plan")
                ent["trial_ends"] = (sub.get("trial_end_time") or "")[:10]
                ent["status"] = sub.get("status")
            res.append(ent)
    return res


def read_pool():
    info = {"total": None, "pw_totp": None, "used": None}
    try:
        accs = json.load(open(GH_PATH, encoding="utf-8"))
        info["total"] = len(accs)
        info["pw_totp"] = sum(1 for a in accs if a.get("password") and (a.get("totp_secret") or a.get("totp")))
    except Exception:
        pass
    try:
        used = open(os.path.join(HOME, "eigent_used_gh.txt"), encoding="utf-8").read().split()
        info["used"] = len(used)
    except Exception:
        info["used"] = 0
    return info


def read_logs(n=25):
    out = {}
    for name in ("farm_cdp.log", "farm.log"):
        p = os.path.join(HOME, name)
        if os.path.exists(p):
            try:
                lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
                out[name] = lines[-n:]
            except Exception as e:
                out[name] = [f"read error: {e}"]
    return out


def http_get(url, headers=None, timeout=15):
    rq = urllib.request.Request(url, headers=headers or {})
    try:
        r = urllib.request.urlopen(rq, timeout=timeout)
        return r.status, r.read()[:500].decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300].decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)[:200]


def probe_proxy():
    """Live proxy check without spending credits."""
    res = {"health": None, "key_info": None}
    for fn in ("eigent_api_creds.json", "eigent_api_creds_free_idx0.json"):
        p = os.path.join(HOME, fn)
        if not os.path.exists(p):
            continue
        try:
            d = json.load(open(p, encoding="utf-8"))
            key = (d.get("key") or {}).get("value") if isinstance(d.get("key"), dict) else d.get("key")
            api_url = ((d.get("key") or {}).get("api_url") if isinstance(d.get("key"), dict) else None) or "https://eigent-proxy.eigent.ai/"
            if not key:
                continue
            base = str(api_url).rstrip("/")
            s, b = http_get(base + "/health/liveliness")
            res["health"] = {"status": s, "body": b[:80]}
            s2, b2 = http_get(base + "/key/info?key=" + str(key), {"Authorization": AUTH + str(key)})
            info = {}
            try:
                j = json.loads(b2)
                ii = j.get("info", j)
                info = {k: ii.get(k) for k in ("max_budget", "spend", "blocked", "expires")}
            except Exception:
                pass
            res["key_info"] = {"status": s2, "info": info, "file": fn}
            break
        except Exception as e:
            res["key_info"] = {"error": str(e)[:150], "file": fn}
    return res


def build_status():
    st = {
        "bank": read_bank(),
        "creds": read_creds(),
        "pool": read_pool(),
        "logs": read_logs(),
        "ts": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
    }
    active = [b for b in st["bank"] if str(b.get("status", "")).upper() == "ACTIVE"]
    st["summary"] = {
        "bank_rows": len(st["bank"]),
        "active_trials": len(active),
        "timeouts": sum(1 for b in st["bank"] if b.get("result") == "TIMEOUT"),
        "gh_pool_free": (st["pool"]["pw_totp"] or 0) - (st["pool"]["used"] or 0),
    }
    return st


CSS = """
body{background:#0d1117;color:#c9d1d9;font-family:Consolas,Menlo,monospace;margin:0;padding:18px}
h1{color:#ff6b35;font-size:20px;margin:0 0 4px}h2{color:#58a6ff;font-size:15px;margin:22px 0 8px;border-bottom:1px solid #21262d;padding-bottom:4px}
.sub{color:#8b949e;font-size:12px;margin-bottom:14px}
.cards{display:flex;gap:12px;flex-wrap:wrap}.card{background:#161b22;border:1px solid #21262d;border-radius:8px;padding:12px 18px;min-width:130px}
.card .v{font-size:24px;color:#3fb950;font-weight:bold}.card .l{font-size:11px;color:#8b949e;margin-top:2px}
table{border-collapse:collapse;width:100%;font-size:12px}td,th{border:1px solid #21262d;padding:4px 8px;text-align:left}th{color:#8b949e;background:#161b22}
pre{background:#161b22;border:1px solid #21262d;border-radius:6px;padding:10px;font-size:11px;overflow-x:auto;white-space:pre-wrap;word-break:break-all}
.ok{color:#3fb950}.bad{color:#f85149}.warn{color:#d29922}
button{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:6px 14px;cursor:pointer;font-family:inherit}
button:hover{border-color:#58a6ff}
"""


def render(st):
    s = st["summary"]
    parts = [f"""<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="30">
<title>Eigent Farm Dashboard</title><style>{CSS}</style></head><body>
<h1>EIGENT FARM DASHBOARD</h1><div class="sub">EIGENT_HOME={html.escape(HOME)} · updated {st['ts']} · auto-refresh 30s</div>
<div class="cards">
<div class="card"><div class="v">{s['active_trials']}</div><div class="l">ACTIVE TRIALS</div></div>
<div class="card"><div class="v">{s['bank_rows']}</div><div class="l">BANK ROWS</div></div>
<div class="card"><div class="v warn">{s['timeouts']}</div><div class="l">TIMEOUTS</div></div>
<div class="card"><div class="v">{s['gh_pool_free']}</div><div class="l">GH POOL FREE (pw+totp)</div></div>
<div class="card"><div class="v">{st['pool']['total'] or '?'}</div><div class="l">GH POOL TOTAL</div></div>
</div>
<button onclick="fetch('/api/probe').then(r=>r.json()).then(d=>document.getElementById('probe').textContent=JSON.stringify(d,null,2))">PROBE PROXY (no spend)</button>
<h2>PROXY LIVE</h2><pre id="probe">click button…</pre>"""]

    parts.append("<h2>API CREDS (masked)</h2><table><tr><th>file</th><th>email</th><th>plan</th><th>status</th><th>trial_ends</th><th>credits</th><th>models</th><th>key</th></tr>")
    for c in st["creds"]:
        cls = "ok" if c.get("status") == "active" else ""
        parts.append(
            f"<tr><td>{html.escape(str(c.get('file')))}</td><td>{html.escape(str(c.get('email')))}</td>"
            f"<td>{html.escape(str(c.get('plan')))}</td><td class='{cls}'>{html.escape(str(c.get('status')))}</td>"
            f"<td>{html.escape(str(c.get('trial_ends')))}</td><td>{html.escape(str(c.get('credits')))}</td>"
            f"<td>{c.get('models')}</td><td>{html.escape(str(c.get('key')))}</td></tr>")
    parts.append("</table>")

    parts.append("<h2>BANK (eigent_bank.jsonl)</h2><table><tr><th>#</th><th>idx</th><th>gh_login</th><th>date</th><th>status/result</th><th>plan</th><th>trial_ends</th><th>spendable</th></tr>")
    for i, b in enumerate(st["bank"]):
        res = b.get("status") or b.get("result") or ""
        cls = "ok" if str(res).upper() == "ACTIVE" else ("bad" if str(res).upper() in ("TIMEOUT", "EXC") else "")
        parts.append(
            f"<tr><td>{i}</td><td>{b.get('idx')}</td><td>{html.escape(str(b.get('gh_login', '')))}</td>"
            f"<td>{html.escape(str(b.get('date', '')))}</td><td class='{cls}'>{html.escape(str(res))}</td>"
            f"<td>{html.escape(str(b.get('plan', '')))}</td><td>{html.escape(str(b.get('trial_ends', '')))}</td>"
            f"<td>{b.get('spendable', '')}</td></tr>")
    parts.append("</table>")

    for name, lines in st["logs"].items():
        parts.append(f"<h2>LOG {html.escape(name)} (tail {len(lines)})</h2><pre>" +
                     html.escape("\n".join(lines)) + "</pre>")
    parts.append("</body></html>")
    return "".join(parts)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self._send(200, render(build_status()), "text/html; charset=utf-8")
        elif self.path.startswith("/api/status"):
            self._send(200, json.dumps(build_status(), ensure_ascii=False, default=str))
        elif self.path.startswith("/api/probe"):
            self._send(200, json.dumps(probe_proxy(), ensure_ascii=False, default=str))
        else:
            self._send(404, json.dumps({"error": "not found"}))


def main():
    print(f"[dashboard] EIGENT_HOME={HOME} port={PORT}", flush=True)
    srv = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[dashboard] http://127.0.0.1:{PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
