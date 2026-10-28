"""Genera index.html del Cancionero de Northwood a partir de Planning Center Services.

Lee las canciones activas (no archivadas), sus tags de tema, sus bases bíblicas
(en las notas de la canción), sus arreglos (tonos con etiqueta, BPM, tempo, letra)
y el historial del servicio dominical (fecha, tono y quién dirigió).

Credenciales: variables de entorno PCO_APP_ID y PCO_SECRET (Personal Access Token).
El historial de domingos se guarda en data/history.json para que cada corrida
solo consulte los domingos nuevos.
"""
import base64, json, os, re, sys, time, urllib.error, urllib.request
from lyric_type import analyze
from datetime import date, datetime, timedelta, timezone

API = "https://api.planningcenteronline.com/services/v2"
SUNDAY_SERVICE_TYPE = os.environ.get("PCO_SERVICE_TYPE", "356734")  # "Sunday Service"
THEME_GROUP = "2971373"   # grupo de tags "Theme" (canciones)
SPEED_GROUP = "774827"    # grupo de tags de velocidad (arreglos)
LEADER_POSITION = "Worship Leader"
HISTORY_START = "2016-01-01"
EXCLUDE_TITLES = {"vocal warm ups"}
HERE = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(HERE, "data", "history.json")

TOKEN = base64.b64encode(f"{os.environ['PCO_APP_ID']}:{os.environ['PCO_SECRET']}".encode()).decode()
_calls = 0


def get(url):
    global _calls
    if not url.startswith("http"):
        url = API + url
    for attempt in range(8):
        req = urllib.request.Request(url, headers={"Authorization": f"Basic {TOKEN}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                _calls += 1
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(int(e.headers.get("Retry-After", "20")) + 1)
                continue
            if e.code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError:
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"No se pudo leer {url}")


def paginate(path):
    url = path
    while url:
        j = get(url)
        yield j
        url = j.get("links", {}).get("next")


# ---------- letra ----------
CH = re.compile(r"^\(?[A-G][#b]?(m|maj|min|sus|dim|aug|add|M)?[0-9]*(\([^)]*\))?([#b]?\d+|sus\d?|add\d|maj\d|omit\d|\+\d*|-\d)*(/[A-G][#b]?)?\)?\*?$")
SECTION = re.compile(r"^(intro|verso|verse|coro|chorus|pre|puente|bridge|tag|outro|interlud|instrumental|final|ending|turn|solo|vamp|melod|notas|acordes|corte|cresc|band|piano|drums)", re.I)


def strip_chordpro(s):
    """Quita acordes en formato ChordPro ([A], [Bb2/D]) y corchetes sueltos."""
    s = re.sub(r"\[[^\]]*\]", "", s)  # acordes completos [A]
    s = re.sub(r"\[[A-G][#b]?(?:maj|min|sus|dim|aug|add|m)?\d*(?:/[A-G][#b]?)?", "", s)  # [Bb2 sin cerrar
    s = s.replace("[", "").replace("]", "")
    return re.sub(r"\s{2,}", " ", s).strip()


def clean_lyrics(txt):
    txt = re.sub(r"<[^>]+>", "", txt or "").replace("{{", "").replace("}}", "")
    out, seen = [], set()
    for line in txt.splitlines():
        s = line.strip()
        if s.startswith("{"):
            continue  # directivas ChordPro: {title: ...}, {c: ...}
        s = strip_chordpro(s)
        if not s or re.search(r"COLUMN_BREAK|PAGE_BREAK|REDEFINE KEY|TRANSPOSE KEY", s):
            continue
        toks = [t for t in re.split(r"[\s|,]+", s) if t]
        if toks and sum(1 for t in toks if CH.match(t) or re.match(r"^(x\d+|\d+x|\d+|[-/*()]+|N\.?C\.?|N/C|M:|BASS|BAJO|MELOD[IÍ]A:?|NOTAS:?|ACORDES:?)$", t, re.I)) >= len(toks) * 0.6:
            continue
        letters = re.sub(r"[^A-Za-zÁÉÍÓÚÑáéíóúñ]", "", s)
        if letters and letters.isupper() and len(letters) > 3:
            continue
        if SECTION.match(s) and len(s) < 60:
            continue
        s = re.sub(r"\s{2,}", " ", s)
        if s.lower() in seen:
            continue
        seen.add(s.lower())
        out.append(s)
    return "\n".join(out)


def parse_bases(notes):
    bases = []
    for line in (notes or "").splitlines():
        line = line.strip()
        if line.startswith("•"):
            ref, _, con = line.lstrip("• ").partition(" — ")
            bases.append([ref.strip(), con.strip()])
    return bases


# ---------- canciones ----------
def load_songs():
    songs = []
    for page in paginate("/songs?per_page=100"):
        for s in page["data"]:
            a = s["attributes"]
            if a.get("hidden") or a["title"].strip().lower() in EXCLUDE_TITLES:
                continue
            songs.append({"id": s["id"], "t": a["title"].strip(), "notes": a.get("notes") or ""})
    print(f"Canciones activas: {len(songs)}")
    out = []
    for i, s in enumerate(songs, 1):
        sid = s["id"]
        tags = []
        for page in paginate(f"/songs/{sid}/tags?per_page=100"):
            for t in page["data"]:
                grp = (((t.get("relationships") or {}).get("tag_group") or {}).get("data") or {}).get("id")
                if grp == THEME_GROUP:
                    tags.append(t["attributes"]["name"])
        arrs, keys, all_keys, speeds, lyr = [], [], [], set(), ""
        for page in paginate(f"/songs/{sid}/arrangements?per_page=25&include=keys"):
            inc = {x["id"]: x["attributes"] for x in page.get("included", []) if x["type"] == "Key"}
            for ar in page["data"]:
                at = ar["attributes"]
                name = at.get("name") or "Arreglo"
                arrs.append({"n": name, "bpm": str(at["bpm"]).rstrip("0").rstrip(".") if at.get("bpm") else ""})
                for kref in ((ar.get("relationships") or {}).get("keys") or {}).get("data") or []:
                    k = inc.get(kref["id"])
                    if not k or not k.get("starting_key"):
                        continue
                    if k["starting_key"] not in all_keys:
                        all_keys.append(k["starting_key"])
                    if (k.get("name") or "").strip():
                        keys.append({"k": k["starting_key"], "l": k["name"].strip(), "a": name})
                for page_t in paginate(f"/songs/{sid}/arrangements/{ar['id']}/tags?per_page=50"):
                    for t in page_t["data"]:
                        grp = (((t.get("relationships") or {}).get("tag_group") or {}).get("data") or {}).get("id")
                        nm = t["attributes"]["name"]
                        if grp == SPEED_GROUP or nm in ("Fast", "Medium", "Slow"):
                            speeds.add({"Fast": "Rápido", "Medium": "Mediano", "Slow": "Lento"}.get(nm, nm))
                if not lyr:
                    lyr = clean_lyrics(at.get("chord_chart") or at.get("lyrics") or "")
        est = False
        if not speeds:
            bpms = [float(a["bpm"]) for a in arrs if a["bpm"]]
            if bpms:
                v = bpms[0]
                speeds.add("Lento" if v <= 85 else "Mediano" if v < 120 else "Rápido")
                est = True
        lt, grp = analyze(lyr, s["t"])
        out.append({
            "lt": lt, "grp": grp,
            "id": sid, "t": s["t"], "tags": tags, "b": parse_bases(s["notes"]),
            "tempo": sorted(speeds), "est": est, "arrs": arrs, "keys": keys, "allKeys": all_keys,
            "multiArr": len({k["a"] for k in keys}) > 1, "lyr": lyr,
        })
        if i % 25 == 0:
            print(f"  {i}/{len(songs)} canciones leídas")
    return out


# ---------- historial dominical ----------
def load_history():
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"plans": {}}


def update_history(hist):
    plans = hist["plans"]
    latest = max((p["d"] for p in plans.values()), default=HISTORY_START)
    # vuelve a leer las últimas 3 semanas por si hubo cambios de último momento
    refresh_from = (datetime.strptime(latest, "%Y-%m-%d") - timedelta(days=21)).strftime("%Y-%m-%d") if plans else HISTORY_START
    base = f"/service_types/{SUNDAY_SERVICE_TYPE}"
    new = 0
    for page in paginate(f"{base}/plans?filter=past&order=-sort_date&per_page=50"):
        stop = False
        for p in page["data"]:
            d = p["attributes"]["sort_date"][:10]
            if d < HISTORY_START or (d < refresh_from and p["id"] in plans):
                stop = True
                break
            items = []
            for ip in paginate(f"{base}/plans/{p['id']}/items?per_page=100"):
                for it in ip["data"]:
                    song = ((it.get("relationships") or {}).get("song") or {}).get("data")
                    if it["attributes"].get("item_type") == "song" and song:
                        items.append([song["id"], it["attributes"].get("key_name") or ""])
            leaders = []
            for mp in paginate(f"{base}/plans/{p['id']}/team_members?per_page=100"):
                for m in mp["data"]:
                    a = m["attributes"]
                    if a.get("team_position_name") == LEADER_POSITION and a.get("status") != "D" and a["name"] not in leaders:
                        leaders.append(a["name"])
            plans[p["id"]] = {"d": d, "items": items, "wl": leaders}
            new += 1
        if stop:
            break
    print(f"Domingos leídos o actualizados: {new}")
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, separators=(",", ":"))


def leader_label(names):
    if not names:
        return ""
    first = [n.split()[0] for n in names]
    if len(first) == 1:
        return first[0]
    if len(first) == 2:
        return f"{first[0]} y {first[1]}"
    return f"{len(first)} líderes"


def last_five(hist):
    by_song = {}
    for p in sorted(hist["plans"].values(), key=lambda p: p["d"], reverse=True):
        for sid, key in p["items"]:
            lst = by_song.setdefault(sid, [])
            if len(lst) < 5 and not any(x[0] == p["d"] for x in lst):
                lst.append([p["d"], key, leader_label(p["wl"])])
    return by_song


MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def main():
    hist = load_history()
    update_history(hist)
    songs = load_songs()
    history = last_five(hist)
    for s in songs:
        s["last"] = history.get(s["id"], [])
    today = datetime.now(timezone(timedelta(hours=-5))).date()
    updated = f"{today.day} de {MESES[today.month - 1]} de {today.year}"
    with open(os.path.join(HERE, "template.html"), encoding="utf-8") as f:
        tpl = f.read()
    html = tpl.replace("__UPDATED__", updated).replace("__DATA__", json.dumps(songs, ensure_ascii=False).replace("</", "<\\/"))
    with open(os.path.join(HERE, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"index.html generado: {len(songs)} canciones, {_calls} consultas a Planning Center.")


if __name__ == "__main__":
    main()
