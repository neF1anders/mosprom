import json,re,html,os
import markdown
SP=os.path.dirname(os.path.abspath(__file__)); OUT=f"{SP}/mosprom"
D=json.loads(open(f"{SP}/pages/data.js",encoding="utf-8").read()[12:-1])
import sys; sys.path.insert(0,SP)
from extra_data import NEW,NEWB,EXTRA
from extra_data2 import NEW2,EXTRA2,RUS,FIXCMU
from extra_data3 import NEW3,EXTRA3,OVER
from detail1 import DET1
from detail2 import DET2
from detail3 import DET3
from extra_data4 import NEW4,EXTRA4
from detail4 import DET4
DET={**DET1,**DET2,**DET3,**DET4}
STAGE_OF={0:4,1:9,2:9,3:5}
for i,r in enumerate(RUS[:4]):
    if i in STAGE_OF: EXTRA2.setdefault(STAGE_OF[i],[]).append(r)
NEW=NEW+NEW2+NEW3+NEW4
for k,v in EXTRA3.items(): EXTRA2.setdefault(k,[]).extend(v)
for k,v in EXTRA4.items(): EXTRA2.setdefault(k,[]).extend(v)
for k,v in EXTRA2.items(): EXTRA[k]=EXTRA.get(k,[])+v
for c in D['comps']:
    if c['n']=='CMU: LLM как эксперт по настройке': c['l']=FIXCMU
for n,c,sc,l,y,u in NEW: D["comps"].append({"n":n,"c":c,"s":sc,"l":l,"y":y,"u":u})
for n,v,note in NEWB: D["builds"].append({"n":n,"v":v,"note":note})
for c in D['comps']:
    if c['n'] in OVER: c['l'],c['y']=OVER[c['n']]
open(f"{OUT}/data.js","w",encoding="utf-8").write("window.DATA="+json.dumps(D,ensure_ascii=False).replace("</","<\\/")+";")
md=open(f"{SP}/site/wiki.md",encoding="utf-8").read()
md=md.replace("(отдельный файл Google Sheets)","(раздел «Сравнение»)").replace("Оценки — из таблицы «fdm\\_components\\_comparison.xlsx» (35 компонентов, пять критериев с пересчитываемыми весами).","Оценки — из раздела «Сравнение».")
secs={}
for p in re.split(r"(?m)^## ",md)[1:]:
    t,_,b=p.partition("\n"); secs[t.strip()]=b.strip()
def conv(b):
    h=markdown.markdown(b,extensions=["tables","fenced_code","sane_lists"])
    h=re.sub(r'<a href="(http[^"]+)"',r'<a href="\1" target="_blank" rel="noopener noreferrer"',h)
    return h.replace("<table>",'<div class="tw"><table>').replace("</table>","</table></div>")
w=[c["w"] for c in D["crit"]]
comp={c["n"]:c for c in D["comps"]}
def score(n):
    c=comp[n]; return round(sum(s*x for s,x in zip(c["s"],w))/sum(w),2)
E=html.escape
# (название в таблице, как показать, лицензия кратко, описание простыми словами)
ST=[
("Чат и связь с ИИ","Есть готовое","Пользователь пишет в чат. ИИ должен уметь управлять слайсером и принтером, для этого ему дают набор команд. Сервер, который публикует эти команды, называется MCP-сервером.","Запрос пользователя (текст, фото, STL)","Команды для ИИ","MCP-серверы управления принтерами и слайсерами",
 [("MCP SDK (Python)","MCP SDK (Python)","MIT","Библиотека, на которой пишется такой сервер. Сама задач печати не решает."),
  ("mcp-3D-printer-server","mcp-3D-printer-server","GPL-2.0","Готовый сервер: работает со многими принтерами и слайсерами, перед стартом просит подтверждение. Умного подбора параметров нет."),
  ("PrusaMCP","PrusaMCP","MIT","Готовый сервер для PrusaSlicer: советует профиль и проверяет модель. Проект помечен как неактивный.")]),
("Получение 3D-модели","Частично","Если у пользователя нет готовой модели (файла STL), её нужно создать по тексту или фото. Есть два пути: нейросеть рисует сетку целиком или ИИ пишет код, который строит деталь с точными размерами.","Текст, фото","Файл STL","Генерация 3D-моделей по тексту и фото",
 [("text-to-cad (earthtojake)","text-to-cad","MIT","Набор навыков для ИИ-агента: текст или картинка → модель → проверка → нарезка в Orca → Bambu. Телеметрия включена по умолчанию."),
  ("CadQuery + LLM","CadQuery + LLM","Apache-2.0","ИИ пишет код, код строит деталь. Размеры точные. Органические формы получаются плохо."),
  ("Meshy","Meshy","Платный сервис","Из текста или фото делает модель примерно за минуту. Точных размеров нет."),
]),
("Проверка и починка модели","Есть готовое + пишем сами","Файл STL проверяют: нет ли дыр, какие размеры и объём. Битую модель чинят. Проверки нависаний и тонких стенок появились только в ранних версиях (augura), зрелого готового модуля нет.","Файл STL","Проверенный STL и отчёт","Анализ и починка STL",
 [("trimesh","trimesh","MIT","Проверка целостности, размеры, объём, простой ремонт."),
  ("augura","augura","Apache-2.0","Проверка печатаемости: нависания, мосты, стенки, ориентация. Ранняя версия, точный анализ только для STEP."),
  ("Tweaker-3","Tweaker-3","GPL-3.0","Подбирает ориентацию модели, чтобы было меньше опор. Вывод только STL.")]),
("Подбор параметров печати","Частично","Нужно выбрать температуру, высоту слоя, заполнение и скорость под цель пользователя: прочность, внешний вид, скорость. Решения появились, но все ранние: бета-версии, эксперименты и научные работы.","Модель, цель, материал, принтер","Набор настроек","Подбор параметров печати",
 [("JusPrin (Obico)","JusPrin","AGPL-3.0, бета","Форк OrcaSlicer с ИИ-чатом: по цели и модели выбирает опоры, слой, brim, разбирает неудачные печати. Windows и macOS."),
  ("Creality Print 7.2 (AI Edition)","Creality Print 7.2","Бесплатно, бета","ИИ-помощник в слайсере: рекомендует параметры с обоснованием, оценивает риски. Только принтеры Creality."),
  ("CMU: LLM как эксперт по настройке","CMU: LLM как эксперт по настройке","Статья, код сырой","Слайсер оценивает результат, ИИ подсказывает, что менять, оптимизатор подбирает. По статье лучшая конфигурация найдена в 78% случаев на 100 деталях. Код есть, но без лицензии, 0 звёзд, нужен ключ OpenAI."),
]),
("Нарезка в G-код","Есть готовое","Слайсер режет модель на слои и выдаёт G-код: команды, которые читает принтер. Слайсер можно запускать без окна, из командной строки.","Модель, настройки","Файл G-код","Слайсеры (CLI) и API принтеров",
 [("OrcaSlicer (CLI)","OrcaSlicer","AGPL-3.0","Есть режим командной строки. Точные флаги мы не проверяли."),
  ("PrusaSlicer (CLI)","PrusaSlicer","AGPL-3.0","Консольный режим известен, но официальную страницу открыть не удалось."),
  ("CuraEngine (CLI)","CuraEngine","Лицензия на странице не указана","Консольный движок Cura: STL → G-код, настройки флагом -s.")]),
("Проверка G-кода","Частично","Перед печатью надо убедиться, что код безопасен: всё внутри стола, температуры допустимые, нет странных команд. Есть отдельные проверки внутри других инструментов, но самостоятельного зрелого валидатора не найдено.","G-код","Разрешение на печать",None,
 [("Kiln: validate_gcode","Kiln: validate_gcode","AGPL-3.0","Блокирует опасные команды и температуры, проверяет по профилю принтера. Лимиты общие: 300 °C сопло, 130 °C стол."),
  ("gcode-lib","gcode-lib","Лицензия «Other»","Разбирает G-код, ищет ходы за границами стола, считает время и расход. Печатаемость не проверяет."),
  ("Навык gcode (text-to-cad)","Навык gcode (text-to-cad)","Лицензия не названа","Проверяет температуры, движения, экструзию и границы стола статически.")]),
("Отправка на принтер","Есть готовое","G-код передают принтеру по сети и запускают. У большинства принтеров для этого есть программа-хост с API.","G-код","Запущенная печать",None,
 [("Moonraker API (Klipper)","Moonraker (Klipper)","Открытый","Загрузка, старт, пауза, отмена, очередь. Сам не режет."),
  ("OctoPrint REST API","OctoPrint","AGPL-3.0","Загрузка, выбор файла, старт, статус."),
  ("PrusaLinkPy","PrusaLinkPy","MIT","Python-клиент PrusaLink: статус, загрузка G-кода, старт, пауза, стоп.")]),
("Несколько принтеров и очередь","Частично","Если принтеров много, нужно выбрать подходящий по размеру стола, материалу и соплу и вести очередь заданий.","Задания","Назначение на принтер","Управление парком принтеров и очередь",
 [("SimplyPrint","SimplyPrint","Облако, закрытый","Общая очередь, подбор принтера по материалу, соплу и столу. Для одного принтера бесплатно."),
  ("Printago Smart Queue","Printago","Облако, закрытый","Очередь выбирает принтер по материалу и тегам, учитывает, что стол очищен."),
  ("FDM Monster","FDM Monster","AGPL-3.0","Сервер для парка OctoPrint и Klipper: сетка принтеров, пакетная печать.")]),
("Наблюдение за печатью","Есть готовое","Камера следит за печатью. Если печать пошла не так, например получилась «лапша», система останавливает её.","Видео с камеры","Остановка или сигнал","Мониторинг и обнаружение дефектов",
 [("Obico","Obico","Открытый","Распознаёт сбои по камере, работает с Klipper и OctoPrint, ставится на свой сервер."),
  ("OctoEverywhere Gadget / Nexus AI","OctoEverywhere","До 3 принтеров бесплатно","Удалённый доступ и распознавание сбоев, есть Bambu."),
  ("OctoPrint-PrintWatch (PrintPal)","PrintWatch (PrintPal)","AGPL-3.0, нужен ключ","Плагин OctoPrint: при дефекте пауза, письмо или SMS, отключение нагрева. Часть функций в бете.")]),
("5D и непланарная печать","Дополнительно","При 5D-печати стол и сопло наклоняются, и слои ложатся не плоско. Это даёт прочность и меньше опор. Готового ИИ для 5D-настроек не найдено.","Модель","G-код для 5 осей","5D и непланарная печать",
 [("S4 Slicer","S4 Slicer","Открытый","Деформирует модель так, чтобы не было нависаний, и пересчитывает G-код. Нужен принтер с 4 осями."),
  ("Fractal Cortex","Fractal Cortex","GPL-3.0","Слайсер для 5 осей: делит модель на части и нарезает в разных направлениях. Только Windows, направления задаёт пользователь."),
  ("Pentos Slicer","Pentos Slicer","GPL-3.0","Браузерный слайсер 5 осей на базе PrusaSlicer. Исследовательский код, коллизии не проверяет.")]),
]

CRN=["Покрытие задачи","Зрелость","Открытость","Встраиваемость","Подтверждённость"]
CAT_DESC={
"Управление принтерами и слайсерами (MCP)":"Готовые MCP-серверы и агенты: ИИ получает команды для слайсера и принтера.",
"Подбор параметров":"Всё, что выбирает температуру, слой, заполнение и опоры под цель пользователя.",
"Мониторинг и дефекты":"Наблюдение за печатью по камере и данные для обучения детекторов дефектов.",
"Управление парком":"Очередь, выбор принтера, учёт пластика и заказов.",
"Генерация моделей":"Получение 3D-модели из текста или фото.",
"Анализ и починка STL":"Проверка и ремонт сетки, печатаемость, ориентация.",
"Слайсеры и API принтеров":"Нарезка в G-код и отправка на принтеры, а также имитаторы принтеров для тестов.",
"Каркас сервера":"Библиотека, на которой пишется наш сервер.",
"5D и непланарная печать":"Слайсеры и методы для печати не плоскими слоями.",
"Проверка G-кода":"Разбор и проверка G-кода перед печатью.",
}
def vword(t):
    return "Брать" if t>=D["thr"]["take"] else "Рассмотреть или взять идею" if t>=D["thr"]["idea"] else "Только как референс"
def sol_html(c,rank=None,label=None,hl=False):
    n=c["n"]; t=score(n); d=DET.get(n)
    rk=""
    if rank: rk=f'<span class="top-tag t{rank}">Топ {rank}</span>'
    if label: rk+=f'<span class="top-tag lab">{E(label)}</span>'
    bars="".join(f'<div class="cr"><span>{CRN[i]}</span><i class="cbar"><b style="width:{v*20}%"></b></i><em>{v}</em></div>' for i,v in enumerate(c["s"]))
    if d:
        body=f'<p><b>Что это.</b> {E(d[0])}</p><p><b>Как пригодится у нас.</b> {E(d[1])}</p><p><b>Ограничения.</b> {E(d[2])}</p>'
    else:
        body=f'<p><b>Что это.</b> {E(c["y"])}</p>'
    return (f'<div class="sd{" best" if (rank or hl) else ""}"><div class="sd-h"><h5>{E(n)}</h5>{rk}<span class="sc sc{round(t)}">{("%.2f"%t).replace(".",",")}</span></div>'
            f'<div class="sd-m"><span class="lic">{E(c["l"])}</span><span class="vd">Вывод по оценке: {vword(t)}</span></div>{body}'
            f'<div class="crs">{bars}</div><a href="{E(c["u"])}" target="_blank" rel="noopener noreferrer">Источник</a></div>')

STCAT={1:["Управление принтерами и слайсерами (MCP)","Каркас сервера"],2:["Генерация моделей"],3:["Анализ и починка STL"],4:["Подбор параметров"],5:["Слайсеры и API принтеров"],6:["Проверка G-кода"],7:["Слайсеры и API принтеров"],8:["Управление парком"],9:["Мониторинг и дефекты"],10:["5D и непланарная печать"]}
def tbl_html(rs):
    rs=sorted(rs,key=lambda c:(-score(c["n"]),c["n"].lower()))
    rows=""
    for k,c in enumerate(rs):
        d=DET.get(c["n"],(c["y"],"",""))
        t=score(c["n"]); tg=f'<span class="top-tag t{k+1}">Топ {k+1}</span> ' if k<3 else ""
        rows+=(f'<tr class="{"tp" if k<3 else ""}"><td>{k+1}</td><td><a href="{E(c["u"])}" target="_blank" rel="noopener noreferrer">{E(c["n"])}</a><br>{tg}</td>'
               f'<td>{E(d[0])}</td><td>{E(d[1])}</td><td>{E(d[2])}</td><td>{E(c["l"])}</td><td class="num">{("%.2f"%t).replace(".",",")}<br><small>{"·".join(str(v) for v in c["s"])}</small></td></tr>')
    return ('<div class="tw"><table class="dt"><thead><tr><th>№</th><th>Решение</th><th>Что это</th><th>Как пригодится у нас</th><th>Ограничения</th><th>Лицензия, версия</th><th>Оценка</th></tr></thead><tbody>'+rows+'</tbody></table></div>'
            '<p class="hint">Оценка от 0 до 5 и пять чисел под ней: покрытие кейса · зрелость · открытость и лицензия · интегрируемость · подтверждённость данных. Оценки субъективны.</p>')


S5={"CuraEngine (CLI)","OrcaSlicer (CLI)","PrusaSlicer (CLI)","Bambu Studio (CLI)","slicer-api (algoz098)","PrusaPATuner (CNC Kitchen)"}
def stage_items(i):
    cs=[c for c in D["comps"] if c["c"] in STCAT[i]]
    if i==5: cs=[c for c in cs if c["n"] in S5]
    if i==7: cs=[c for c in cs if c["n"] not in S5]
    byurl={c["u"]:c for c in D["comps"]}
    ex=[]
    for n,u,t,ok in EXTRA.get(i,[]):
        if u in byurl:
            c=byurl[u]
            if c not in cs: cs.append(c)
        else: ex.append((n,u,t,ok))
    return cs,ex
def stage_table(i):
    cs,ex=stage_items(i)
    cs=sorted(cs,key=lambda c:(-score(c["n"]),c["n"].lower()))
    rows=""
    for k,c in enumerate(cs):
        d=DET.get(c["n"])
        t=score(c["n"]); tg=f'<span class="top-tag t{k+1}">Топ {k+1}</span> ' if k<3 else ""
        if d: txt=f'<p><b>Что это.</b> {E(d[0])}</p><p><b>Как пригодится у нас.</b> {E(d[1])}</p><p><b>Ограничения.</b> {E(d[2])}</p>'
        else: txt=f'<p>{E(c["y"])}</p>'
        rows+=(f'<tr class="{"tp" if k<3 else ""}"><td>{k+1}</td><td><a href="{E(c["u"])}" target="_blank" rel="noopener noreferrer">{E(c["n"])}</a><br>{tg}</td><td>{txt}</td><td>{E(c["l"])}</td><td class="num">{("%.2f"%t).replace(".",",")}<br><small>{"·".join(str(v) for v in c["s"])}</small></td></tr>')
    n0=len(cs)
    for j,(n,u,t,ok) in enumerate(ex):
        nm=f'<a href="{E(u)}" target="_blank" rel="noopener noreferrer">{E(n)}</a>' if u else f'<b>{E(n)}</b>'
        flag="" if ok else " <em>Не проверено: сведения только из выдачи или с оговорками.</em>"
        rows+=f'<tr><td>{n0+j+1}</td><td>{nm}</td><td><p>{E(t)}{flag}</p></td><td>см. описание</td><td class="num">без оценки</td></tr>'
    return len(cs)+len(ex),('<div class="tw"><table class="dt"><thead><tr><th>№</th><th>Решение</th><th>Описание</th><th>Лицензия, версия</th><th>Оценка</th></tr></thead><tbody>'+rows+'</tbody></table></div>'
        f'<p class="hint">Сначала решения с оценкой (в порядке убывания), первые три помечены «Топ». Ниже — найденное без оценки: у них нет пяти оценок, только описание. Оценка от 0 до 5, пять чисел под ней: покрытие кейса · зрелость · открытость и лицензия · интегрируемость · подтверждённость данных. Они субъективны, расчёт описан в начале страницы.</p>')

def cats_html():
    order=[]
    for c in D["comps"]:
        if c["c"] not in order: order.append(c["c"])
    out=""
    for cat in order:
        rs=sorted([c for c in D["comps"] if c["c"]==cat],key=lambda c:(-score(c["n"]),c["n"].lower()))
        avg=sum(score(c["n"]) for c in rs)/len(rs)
        top="".join(f'<li><span class="pl">{k+1}</span><a href="{E(c["u"])}" target="_blank" rel="noopener noreferrer">{E(c["n"])}</a><span class="pv">{("%.2f"%score(c["n"])).replace(".",",")}</span></li>' for k,c in enumerate(rs[:3]))
        det=tbl_html(rs)
        out+=(f'<div class="cat-card"><h4>{E(cat)}</h4><p class="cd">{E(CAT_DESC.get(cat,""))}</p><div class="avg">{("%.2f"%avg).replace(".",",")} <small>средняя оценка, решений: {len(rs)}</small></div>'
              f'<ol class="top3">{top}</ol><details class="catdet"><summary>Статья подробнее: разбор всех решений ({len(rs)})</summary>{det}</details></div>')
    return out

def card(i,t,badge,what,inp,out,art,sols):
    pass
    s=""
    if sols:
        s='<div class="sol">'
        for key,name,lic,txt in sols:
            c=comp[key]
            s+=f'<div><b>{E(name)}</b><span class="lic">{E(lic)}</span><p>{E(txt)}</p><span class="sc sc{round(score(key))}">{("%.2f" % score(key)).replace(".",",")}</span><a href="{E(c["u"])}" target="_blank" rel="noopener noreferrer">Источник</a></div>'
        s+="</div>"
    else:
        s='<div class="none">Не найдено. Этот этап пишем сами.</div>'
    note=""
    cnt,tb=stage_table(i)
    det=f'<details><summary>Подробная статья: все найденные решения этапа ({cnt})</summary><div class="art">{tb}</div></details>'
    tot=f'<p class="total">Всего найдено: <b>{cnt}</b></p>'
    ex=tot
    return f'<article class="stage" id="s{i}"><h3><span class="n">{i:02d}</span>{E(t)} <span class="badge b-{"take" if badge.startswith("Есть") else "part" if badge in("Частично","Дополнительно") else "own"}">{E(badge)}</span></h3><p class="what">{E(what)}</p><p class="hint">Вход: {E(inp)}. Выход: {E(out)}.</p>{ex}{det}</article>'
cards="".join(card(i+1,*x) for i,x in enumerate(ST))
flow="".join(f'<a href="#s{i+1}"><span>{i+1:02d}</span>{E(x[0])}</a>' for i,x in enumerate(ST))
rows="".join(f'<tr><td>{i+1}</td><td><a href="#s{i+1}">{E(x[0])}</a></td><td>{E(x[3])}</td><td>{E(x[4])}</td><td class="st">{E(x[1])}</td></tr>' for i,x in enumerate(ST))
cov=sorted(((sum(b["v"])/len(b["v"]),b["n"]) for b in D["builds"]),reverse=True)
lead=f"{cov[0][1]} ({round(cov[0][0]*100)}% функций)"
nbuilds=len(D["builds"]); ncomp=len(D["comps"])
srcs="".join(re.findall(r"<li>.*?</li>",conv(secs["Источники"]),flags=re.S))
seen=set(re.findall(r'href="([^"]+)"',srcs)); add=[]
for n,c,sc,l,y,u in NEW:
    if u not in seen: seen.add(u); add.append((n,u))
for n,u,t,ok in RUS:
    if u not in seen: seen.add(u); add.append((n,u))
for k,v in EXTRA.items():
    for n,u,t,ok in v:
        if u and u not in seen: seen.add(u); add.append((n,u))
new4={c[5] for c in NEW4}|{e[1] for v in EXTRA4.values() for e in v}
srcs+="".join(f'<li><a href="{E(u)}" target="_blank" rel="noopener noreferrer">{E(n)}</a> (добавлено {"23.10" if u in new4 else "21.10"})</li>' for n,u in add)
src_intro=secs["Источники"].split("\n\n")[0]
builds_txt=conv(secs["Цельные сборки и конкуренты"])
def head(h,p=""): return f'<div class="sh"><h2>{h}</h2>'+(f"<p>{p}</p>" if p else "")+"</div>"
NAV=[("task","Задача"),("arch","Архитектура"),("stages","Этапы"),("builds","Сборки"),("sources","Источники")]
nav="".join(f'<a href="#{i}">{l}</a>' for i,l in NAV)
crit_rows="".join(f'<tr><td>{E(c["name"])}</td><td>{str(c["w"]).replace(".",",")}</td><td>{E(c["desc"])}</td></tr>' for c in D["crit"])
page=f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mosprom Wiki</title>
<meta name="description" content="Mosprom Wiki: этапы ИИ-сервиса подбора параметров FDM-печати, готовые решения и сравнение.">
<meta name="theme-color" content="#07090d">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%2307090d'/%3E%3Cpath d='M8 22l8-14 8 14z' fill='none' stroke='%232ee6a6' stroke-width='2.5'/%3E%3C/svg%3E">
<link rel="stylesheet" href="style.css"></head><body>
<a class="skip" href="#main">К содержимому</a>
<header class="top"><div class="top-in"><a class="logo" href="#top">Mosprom Wiki</a><nav aria-label="Разделы">{nav}</nav></div></header>
<div class="hero" id="top"><div class="hero-in"><h1>Mosprom Wiki</h1><p class="sub">Сервис, который сам подбирает параметры FDM-печати: что входит в задачу, из каких этапов она состоит и какие готовые решения есть для каждого этапа.</p></div></div>
<main id="main">
<section class="blk" id="task">{head("Что в задаче")}
<p>Нужен сервис с чатом. Пользователь загружает модель (STL), фото и пишет, что хочет получить. Сервис сам выбирает настройки печати, делает G-код, отправляет его на нужный принтер и следит за печатью.</p>
<div class="grid g2" style="margin:16px 0">
<div class="card"><h3>Вход</h3><p>Файл STL, фото, текстовый запрос.</p></div>
<div class="card"><h3>Выход</h3><p>Настройки печати, готовый G-код, запущенная печать на принтере из парка.</p></div></div>

<h3>Как считается оценка</h3>
<p>У каждого решения есть пять оценок от 0 до 5. Это целые числа, которые я поставил сам по прочитанным страницам проектов, поэтому они субъективны. Итог — взвешенное среднее: каждая оценка умножается на свой вес, результаты складываются.</p>
<div class="tw"><table><thead><tr><th>Критерий</th><th>Вес</th><th>Что оценивается</th></tr></thead><tbody>{crit_rows}</tbody></table></div>
<p class="formula"><code>Оценка = 0,30 × Покрытие кейса + 0,20 × Зрелость + 0,15 × Открытость и лицензия + 0,20 × Интегрируемость + 0,15 × Подтверждённость данных</code></p>
<p>Веса в сумме дают 1, поэтому итог тоже лежит в пределах от 0 до 5. Пример: у Kiln оценки 4, 3, 2, 5, 2, итог = 1,2 + 0,6 + 0,3 + 1,0 + 0,3 = 3,40.</p>
<p>Как читать шкалу каждого критерия: 5 — полностью соответствует, 3 — частично или есть оговорки, 1 — почти нет, 0 — нет. Что означает итог: от 3,5 и выше — «Брать», от 2,5 до 3,5 — «Рассмотреть или взять идею», ниже 2,5 — «Только как референс». Если оценки равны, решения упорядочены по названию. В таблицах этапов первые три строки помечены «Топ 1–3».</p>
<p>Оценка не измеряет качество работы решения. Она показывает, насколько оно подходит для нашей задачи и насколько мы уверены в сведениях о нём. Если источник не удалось проверить, это написано в тексте, а «Подтверждённость» снижена.</p>
<h3>Термины</h3>
<div class="terms"><div><b>STL</b>файл с 3D-моделью.</div><div><b>Слайсер</b>программа, которая режет модель на слои и делает G-код (Cura, PrusaSlicer, OrcaSlicer).</div><div><b>G-код</b>файл с командами, которые выполняет принтер.</div><div><b>FDM</b>печать пластиковой нитью, расплавленной в сопле.</div><div><b>5D-печать</b>стол и сопло наклоняются, слои идут не плоско.</div><div><b>MCP-сервер</b>программа, через которую ИИ получает команды для управления программами и принтерами.</div></div></section>
<section class="blk" id="arch">{head("Архитектура","Запрос проходит десять этапов по порядку. Нажмите на этап, чтобы перейти к описанию.")}
<div class="flow2">{flow}</div>
<div class="tw"><table><thead><tr><th>№</th><th>Этап</th><th>Вход</th><th>Выход</th><th>Статус</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="hint">Статус: «Есть готовое» значит, что можно взять существующий инструмент. «Пишем сами» значит, что готового решения не найдено. Целиком всю цепочку не закрывает ни одно найденное решение; ближе всего {E(lead)}. Для подбора параметров по цели ближе всего JusPrin (бета).</p></section>
<section class="blk" id="stages">{head("Этапы и готовые решения","По каждому этапу: что это, три готовых решения и подробная статья. Число рядом с решением — оценка из таблицы, от 0 до 5.")}{cards}</section>
<section class="blk" id="builds">{head("Цельные сборки и конкуренты")}
<div class="panel-art" style="margin-bottom:20px"><div class="callout">Обновление 23 октября 2026: добавлены 58 компонентов и 114 находок из репозиториев, статей и наборов данных (prusaslicer-tuner, hermes-orcaslicer, bambuddy, статьи про подбор по задаче и проверку G-кода). Обновление 21 октября 2026. Добавлены JusPrin (ИИ-чат в OrcaSlicer: цель, настройки, нарезка) и text-to-cad (текст или картинка → модель → нарезка → Bambu). Всю цепочку вместе с парком принтеров и мониторингом по-прежнему не закрывает ни одно найденное решение.</div>{builds_txt}</div>
</section>
<section class="blk" id="sources">{head("Источники")}<p>{E(src_intro)}</p>
<input type="search" id="srcQ" placeholder="Фильтр источников" aria-label="Фильтр источников" style="width:100%;max-width:420px"><ul class="src" id="srcList">{srcs}</ul></section>
</main>
<footer><span>Mosprom Wiki. Данные на 23 октября 2026. Оценки субъективны.</span></footer>
<script src="data.js"></script><script src="app.js"></script></body></html>'''
open(f"{OUT}/index.html","w",encoding="utf-8").write(page)
open(f"{OUT}/.nojekyll","w").close()
open(f"{OUT}/README.md","w",encoding="utf-8").write("# Mosprom Wiki\n\nСтатичный сайт: index.html, style.css, app.js, data.js, .nojekyll. Загрузите ВСЕ файлы в корень репозитория GitHub, затем Settings → Pages → Deploy from a branch → main → / (root).\n")
print("ok",len(page),nbuilds)
