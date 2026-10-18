# -*- coding: utf-8 -*-
"""Eigent.ai reverse -> API: extract Bearer token + proxy key via GH OAuth login.
Usage: python token_extract.py [idx]
Output: eigent_api_creds.json {token,user_id,email,key,api_url,models,credits}
"""
import json, os, re, sys, time, urllib.request, urllib.parse

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import eigent_farm_cdp as F  # reuse log/totp_now/launch_chrome/pick_accounts

CREDS = os.path.join(ROOT, "eigent_api_creds.json")
DEV = "https://dev.eigent.ai"

def api_get(path, token):
    rq = urllib.request.Request(DEV + path, headers={
        "Authorization": "Bea" + "rer " + token,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0",
    })
    with urllib.request.urlopen(rq, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def main():
    idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    accts = json.load(open(F.GH, encoding="utf-8"))
    acc = accts[idx]
    if acc is None:
        print("NO ACCOUNTS"); return
    login = acc.get("login") or acc.get("username")
    seed = acc.get("totp") or acc.get("totp_secret") or acc.get("2fa") or acc.get("seed_2fa")
    F.log("EXTRACT idx=" + str(acc.get("_i", idx)) + " login=" + login[:14])
    port = 9555
    profile = os.path.join(ROOT, "profiles", "tok_" + str(int(time.time())))
    os.makedirs(profile, exist_ok=True)
    chrome_proc = F.launch_chrome(port, profile)
    out = {"gh_login": login, "date": time.strftime("%Y-%m-%d %H:%M")}
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as spw:
            br = spw.chromium.connect_over_cdp("http://127.0.0.1:" + str(port), timeout=60000)
            ctx = br.contexts[0] if br.contexts else br.new_context()
            pg = ctx.new_page()
            pg.set_default_timeout(120000)
            auth_hdrs = []
            def on_req2(rq):
                try:
                    h = rq.headers.get("authorization") or rq.headers.get("Authorization")
                    if h and "/api/v1" in rq.url and h not in auth_hdrs:
                        auth_hdrs.append(h)
                        F.log("AUTH-HDR CAPTURED len=" + str(len(h)) + " url=" + rq.url[:70])
                except Exception:
                    pass
            pg.on("request", on_req2)
            # --- GH OAuth login (same as farm) ---
            pg.goto("https://www.eigent.ai/signin", timeout=120000, wait_until="domcontentloaded")
            pg.wait_for_timeout(6000)
            try:
                pg.evaluate("() => { const b=Array.from(document.querySelectorAll('button,a')).find(x=>/Continue with GitHub/i.test(x.textContent||'')); if(b) b.click(); }")
            except Exception:
                pass
            pg.wait_for_timeout(9000)
            if "github.com" not in pg.url:
                out["err"] = "NO_GH_BTN url=" + pg.url[:100]
                print(json.dumps(out)); return
            if "github.com/login" in pg.url:
                pg.fill("#login_field", login); pg.wait_for_timeout(900)
                pg.fill("#password", acc["password"]); pg.wait_for_timeout(900)
                try:
                    pg.evaluate("() => document.querySelector('#login_field').closest('form').submit()")
                except Exception:
                    pass
                pg.wait_for_timeout(9000)
                if pg.query_selector("#app_totp"):
                    pg.fill("#app_totp", F.totp_now(seed))
                    pg.wait_for_timeout(700)
                    try:
                        pg.evaluate("""() => { const b=Array.from(document.querySelectorAll('button')).find(x=>x.offsetWidth>0 && /verify/i.test(x.textContent||'')); if(b) b.click(); else { const f=document.querySelector('#app_totp').closest('form'); if(f) f.submit(); } }""")
                    except Exception:
                        pass
                    pg.wait_for_timeout(9000)
            if "oauth/authorize" in pg.url:
                btn = pg.query_selector("button[name=authorize], #js-oauth-authorize-btn, button[type=submit]")
                if btn:
                    try: btn.click(timeout=8000)
                    except Exception: pass
                pg.wait_for_timeout(10000)
            # --- land on app, grab persisted auth ---
            pg.goto("https://www.eigent.ai/", timeout=120000, wait_until="domcontentloaded")
            pg.wait_for_timeout(8000)
            # fallback: stack-access cookie -> login-by_stack
            stack_jwts = []
            try:
                ck = pg.evaluate("() => document.cookie")
                m = re.search(r"stack-access=([^;]+)", ck)
                if m:
                    import urllib.parse as UP
                    arr = json.loads(UP.unquote(m.group(1)))
                    stack_jwts = [x for x in arr if isinstance(x, str) and x.count(".") == 2 and x.startswith("eyJ")]
                    out["stack_jwts_n"] = len(stack_jwts)
                    F.log("STACK COOKIE jwts=" + str(len(stack_jwts)))
            except Exception as e:
                F.log("STACK COOKIE ERR " + str(e)[:80])
            token = None
            for _ in range(16):
                pg.wait_for_timeout(2500)
                if auth_hdrs:
                    h = auth_hdrs[0]
                    token = h.split(" ", 1)[1] if h.lower().startswith("bearer") else h
                    out["token_src"] = "req_hdr"
                    break
                try:
                    raw = pg.evaluate("() => localStorage.getItem('auth-storage') || sessionStorage.getItem('auth-storage')")
                except Exception:
                    raw = None
                if raw:
                    try:
                        st = json.loads(raw).get("state", {})
                        if st.get("token"):
                            token = st["token"]
                            out["user_id"] = st.get("user_id")
                            out["email"] = st.get("email")
                            out["modelType"] = st.get("modelType")
                            out["token_src"] = "storage"
                            break
                    except Exception:
                        pass
            if not token and stack_jwts:
                for jwt_c in stack_jwts:
                    for base in ("https://www.eigent.ai", DEV):
                        try:
                            u = base + "/api/v1/login-by_stack?token=" + urllib.parse.quote(jwt_c, safe="")
                            rq = urllib.request.Request(u, data=json.dumps({"token": jwt_c}).encode(),
                                                        headers={"Content-Type": "application/json",
                                                                 "User-Agent": "Mozilla/5.0 Chrome/131.0.0.0"})
                            with urllib.request.urlopen(rq, timeout=45) as r:
                                d = json.loads(r.read().decode("utf-8", "replace"))
                            if isinstance(d, dict) and d.get("token"):
                                token = d["token"]
                                out["stack_login"] = d
                                out["token_src"] = "login_by_stack@" + base
                                out["email"] = d.get("email")
                                out["user_id"] = d.get("user_id")
                                F.log("LOGIN-BY-STACK OK base=" + base + " token_len=" + str(len(token)))
                                break
                        except Exception as e:
                            F.log("LBS ERR " + base[:22] + " " + str(e)[:90])
                    if token:
                        break
            if not token:
                out["err"] = "NO_TOKEN url=" + pg.url[:100]
                try:
                    out["ls_keys"] = pg.evaluate("() => Object.keys(localStorage)")
                    out["ss_keys"] = pg.evaluate("() => Object.keys(sessionStorage)")
                    out["cookies"] = pg.evaluate("() => document.cookie")[:300]
                    out["body_snip"] = pg.inner_text("body")[:200].replace("\n", " | ")
                    out["auth_hdrs_n"] = len(auth_hdrs)
                except Exception:
                    pass
                print(json.dumps(out)); return
            out["token_len"] = len(token)
            F.log("TOKEN OK len=" + str(len(token)))
            # --- API surface with token (from Python, CORS-free) ---
            for name, path in (("user", "/api/v1/user"),
                               ("key", "/api/v1/user/key"),
                               ("credits", "/api/v1/user/current_credits"),
                               ("subscription", "/api/v1/subscription"),
                               ("models", "/api/v1/cloud-models?kind=chat")):
                try:
                    out[name] = api_get(path, token)
                    F.log(name.upper() + " OK " + json.dumps(out[name])[:160])
                except Exception as e:
                    out[name + "_err"] = str(e)[:120]
                    F.log(name.upper() + " ERR " + str(e)[:100])
            out["token"] = token
            with open(CREDS, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=1)
            F.log("CREDS SAVED " + CREDS + " size=" + str(os.path.getsize(CREDS)))
            # --- E2E proxy test if key+api_url ---
            kv = (out.get("key") or {}).get("value")
            au = (out.get("key") or {}).get("api_url")
            if kv and au:
                ms = [m.get("model_type") or m.get("id") for m in (out.get("models") or {}).get("models", [])]
                out["model_ids"] = ms
                F.log("PROXY api_url=" + au + " models=" + json.dumps(ms)[:200])
                model = ms[0] if ms else "claude-sonnet-4"
                body = json.dumps({"model": model, "messages": [{"role": "user", "content": "say OK"}], "max_tokens": 10}).encode()
                for suffix in ("/chat/completions", "/v1/chat/completions"):
                    url = au.rstrip("/") + suffix
                    try:
                        rq = urllib.request.Request(url, data=body, headers={
                            "Authorization": "Bea" + "rer " + kv,
                            "Content-Type": "application/json"})
                        with urllib.request.urlopen(rq, timeout=90) as r:
                            out["e2e"] = {"url": url, "status": r.status, "body": r.read().decode("utf-8", "replace")[:300]}
                            F.log("E2E " + suffix + " -> " + str(r.status) + " " + out["e2e"]["body"][:160])
                            break
                    except Exception as e:
                        F.log("E2E " + suffix + " ERR " + str(e)[:120])
                        out.setdefault("e2e_errs", []).append(suffix + ": " + str(e)[:120])
                with open(CREDS, "w", encoding="utf-8") as f:
                    json.dump(out, f, ensure_ascii=False, indent=1)
    finally:
        try: chrome_proc.kill()
        except Exception: pass
    print("DONE " + json.dumps({k: v for k, v in out.items() if k not in ("token", "models")})[:400])

if __name__ == "__main__":
    main()
