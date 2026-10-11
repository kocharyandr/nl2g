"""Открывает чат в видимом Chrome (CDP :9333) и ведёт диалог; окно остаётся открытым.
   Запуск: drive2.py open              — открыть окно, включить «Данные из базы»
           drive2.py send "текст" tag  — отправить сообщение в уже открытое окно
           drive2.py approve tag       — нажать «Подтвердить»
           drive2.py shot tag          — скриншот"""
import sys, time, subprocess, os
from pathlib import Path
from playwright.sync_api import sync_playwright

URL, CDP, OUT = "http://127.0.0.1:7861", "http://127.0.0.1:9333", Path(__file__).parent
STEP_TIMEOUT = 900

def log(m): print(time.strftime("%H:%M:%S"), m, flush=True)
def bot_rows(p): return p.evaluate("document.querySelectorAll('#chatbot .bot-row').length")
def busy(p): return p.evaluate("!!document.querySelector('.generating, .progress-bar, .pending')")
def last_bot(p): return p.evaluate("""() => { const r=[...document.querySelectorAll('#chatbot .bot-row')].pop();
  return r ? r.innerText.replace(/\\n+/g,' | ').slice(0,400) : '' }""")

def wait_done(p, before, tag):
    t0 = time.time()
    while time.time() - t0 < STEP_TIMEOUT:
        p.wait_for_timeout(2000)
        if bot_rows(p) > before and not busy(p):
            p.wait_for_timeout(1500)
            if not busy(p):
                log(f"{tag}: готово за {time.time()-t0:.0f}с"); return
    raise TimeoutError(tag)

def shot(p, tag):
    p.evaluate("""() => { let el=[...document.querySelectorAll('#chatbot .bot-row')].pop();
      while (el) { if (el.scrollHeight > el.clientHeight + 4) el.scrollTop = el.scrollHeight; el = el.parentElement; }
      window.scrollTo(0, document.body.scrollHeight); }""")
    p.wait_for_timeout(700); p.screenshot(path=str(OUT / f"{tag}.png"))

cmd = sys.argv[1]
if cmd == "open":
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    prof = OUT / "chrome-profile"
    subprocess.Popen([chrome, f"--remote-debugging-port=9333", f"--user-data-dir={prof}", "--no-first-run",
                      "--window-size=1280,1000", URL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(4)

with sync_playwright() as pw:
    browser = pw.chromium.connect_over_cdp(CDP)
    page = [pg for ctx in browser.contexts for pg in ctx.pages if "7861" in pg.url][0]
    if cmd == "open":
        page.wait_for_selector("#send_btn", timeout=30000)
        cb = page.get_by_label("Данные из базы")
        if not cb.is_checked(): cb.check()
        log("окно открыто, «Данные из базы» включено"); shot(page, "00_start")
    elif cmd == "send":
        text, tag = sys.argv[2], sys.argv[3]
        before = bot_rows(page)
        box = page.locator("#chat_input textarea"); box.click(); box.fill(text)
        page.wait_for_timeout(300); page.locator("#send_btn").click(); log(f"отправлено: «{text}»")
        wait_done(page, before, tag); shot(page, tag); log("бот: " + last_bot(page))
    elif cmd == "approve":
        tag = sys.argv[2]; page.locator("#approve_btn").click(); log("нажал «Подтвердить»")
        page.wait_for_timeout(3000); shot(page, tag)
        log("approve_btn visible=%s" % page.locator("#approve_btn").is_visible())
    elif cmd == "new":
        page.goto(URL, wait_until="domcontentloaded"); page.wait_for_selector("#send_btn", timeout=30000)
        page.wait_for_timeout(1500); cb = page.get_by_label("Данные из базы")
        if not cb.is_checked(): cb.check()
        log("новая сессия, «Данные из базы» включено")
    elif cmd == "shot":
        shot(page, sys.argv[2]); log("скриншот " + sys.argv[2])
