import subprocess,time
from playwright.sync_api import sync_playwright
srv=subprocess.Popen(["python3","-m","http.server","8771","-d","mosprom"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);time.sleep(1)
try:
  with sync_playwright() as p:
    b=p.chromium.launch()
    for w,h in((1366,900),(390,844)):
        pg=b.new_page(viewport={"width":w,"height":h});errs=[]
        pg.on("pageerror",lambda e:errs.append(str(e)));pg.on("console",lambda m:m.type=="error" and errs.append(m.text))
        pg.goto("http://localhost:8771/index.html");pg.wait_for_timeout(500)
        print(w,"errors",errs,"cats",pg.locator(".catlist>.cat-card").count(),"sd",pg.locator(".catlist .sd").count(),"top",pg.locator(".catlist .sd.best").count(),"stage sd",pg.locator(".stage .sd").count())
        print(" overflow",pg.evaluate("document.documentElement.scrollWidth>innerWidth"))
        pg.locator(".catdet").first.evaluate("e=>e.open=true")
        pg.locator("#compare").scroll_into_view_if_needed();pg.locator(".catlist .cat-card").first.scroll_into_view_if_needed()
        pg.wait_for_timeout(200);pg.screenshot(path=f"c_{w}.png")
        pg.locator(".stage").nth(3).locator("details>summary").last.click() if False else None
        pg.evaluate("document.querySelectorAll('.stage>details').forEach(d=>d.open=true)")
        pg.locator("#s4").scroll_into_view_if_needed();pg.screenshot(path=f"s4_{w}.png")
        print(" overflow after open",pg.evaluate("document.documentElement.scrollWidth>innerWidth"))
    b.close()
finally: srv.terminate()
