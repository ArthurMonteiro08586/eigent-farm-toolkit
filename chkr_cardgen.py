# chkr.cc card generator — OFFLINE port (BIN 5424322339, the BIN that passes Stripe on eigent.ai)
# chkr.cc's /bin-generator page generates cards CLIENT-SIDE (Astro SPA); live-check endpoints
# (api.chkr.cc/...) return 429 from most IPs and are NOT needed — Luhn-valid card is enough
# for the eigent Pro trial checkout.
# Usage: python chkr_cardgen.py [count]  -> prints JSON list of {pan, exp, cvv}
import random, sys, json, os

BIN = os.environ.get("BIN_OVERRIDE", "5424322339")

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
            return {"pan": p, "exp": str(mm).zfill(2) + "/" + str(yy), "cvv": cvv}
    raise RuntimeError("luhn gen fail")

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    print(json.dumps([gen_card() for _ in range(n)], indent=1))
