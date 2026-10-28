"""Clasifica la letra de una canción por tipo (objetiva, subjetiva, reflexiva) y detecta si es grupal.

Definiciones (Northwood Worship):
- Objetiva: se centra en el carácter de Dios y sus obras.
- Subjetiva: se centra en mí (mi situación, mis decisiones).
- Reflexiva: se centra en lo que estamos haciendo al adorar ("Levantemos nuestras manos y adoremos").
- Grupal: la letra habla desde la congregación entera ("nosotros", "nuestro", "cantamos").

Se clasifica línea por línea con reglas simples en español e inglés; el resultado es
una proporción aproximada, pensada para orientar, no para ser exacta.
"""
import re
import unicodedata


def _norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


# Verbos del acto de adorar (raíces), en español e inglés
WORSHIP_ROOTS = (
    "cant", "alab", "ador", "exalt", "glorific", "bendec", "bendig", "aclam", "danz", "grit", "aplaud",
    "postr", "rind", "rendir", "levant", "alz", "elev", "entreg", "ofrec", "celebr", "proclam", "declar", "honr", "magnific", "corone",
    "sing", "prais", "worship", "lift", "rais", "shout", "danc", "bow", "glorif", "exalt", "clap",
    "bless", "declare", "proclaim", "magnif", "celebrat",
)
# Formas que indican que el sujeto hace la acción ahora o se exhorta a hacerla
HORTATIVE = re.compile(r"\b(vamos a|venid|ven a|vengan|oh pueblo|pueblos todos|let us|let's|come let)\b")

DIVINE = r"(dios|senor|rey|jesus|cristo|salvador|redentor|padre|amado|pastor|creador|libertador|amigo|todo|refugio|roca|fortaleza|esperanza|god|lord|king|savior|saviour|jesus|christ|father|shepherd|redeemer|rock|everything)"
SG_POSSESSIVE_OF_GOD = re.compile(rf"\b(mi|my)\s+(buen\s+|gran\s+|unico\s+)?{DIVINE}\b")

SG_WORDS = re.compile(r"\b(yo|me|mi|mis|mio|mia|conmigo|i|i'm|i've|i'll|me|my|mine|myself)\b")
SG_VERBS = re.compile(r"\b(soy|estoy|tengo|quiero|puedo|vengo|voy|se|creo|confio|necesito|busco|siento|entrego|vivo|camino|"
                      r"corro|anhelo|espero|pido|clamo|amo|doy|traigo|encuentro|encontre|cai|perdi|estaba|fui|era|tenia|"
                      r"\w+are|\w+ere|\w+ire)\b")
PL_WORDS = re.compile(r"\b(nosotros|nosotras|nos|nuestro|nuestra|nuestros|nuestras|we|we're|we've|we'll|us|our|ours)\b")
PL_VERBS = re.compile(r"\b\w+(amos|emos|imos)\b")
# 1a persona singular pegada al verbo: "lléname", "dame", "guíame", "renuévame"
SG_CLITIC = re.compile(r"\b(?!sublime\b)\w*[aei]me\b|\bdame\b")
# adorar dirigido a Dios en infinitivo o con sustantivo: "para adorarte", "darte adoración", "recibe nuestra alabanza"
WORSHIP_TO_GOD = re.compile(r"\b\w+(arte|erte|irte|arle|erle|irle)\b|\b(adoracion|alabanza|alabanzas|honra|ofrenda)\b")
GOD_FOCUS = re.compile(rf"\b(tu|tus|eres|es|el|su|sus|te|ti|contigo|{DIVINE}|you|your|you're|he|his|him|santo|digno|grande|fiel|poderoso|"
                       r"holy|worthy|great|faithful|mighty|almighty|reina|reinas|reinara|vencio|resucito|murio|salva|sana)\b")


def classify_line(line):
    n = _norm(line)
    words = n.split()
    if not words:
        return None, False, False
    n_wo_god_pos = SG_POSSESSIVE_OF_GOD.sub(" ", n)
    sg = bool(SG_WORDS.search(n_wo_god_pos) or SG_VERBS.search(n_wo_god_pos) or SG_CLITIC.search(n_wo_god_pos))
    pl = bool(PL_WORDS.search(n) or PL_VERBS.search(n))
    has_worship = any(re.search(rf"\b{r}\w*", n) for r in WORSHIP_ROOTS)
    worship_act = (has_worship and (sg or pl or HORTATIVE.search(n) or WORSHIP_TO_GOD.search(n))) or (
        re.search(r"\b(adoracion|alabanza|alabanzas)\b", n) and re.search(r"\b(da|dar|darte|damos|doy|traigo|traemos|recibe|ofrezco|ofrecemos|llenar)\b", n)) or (
        has_worship and re.search(r"\b(canta|alaba|adora|exalta|aplaudan|griten|alabad|cantad|bendice|sing|praise|shout|lift|raise)\b", n)
    )
    if worship_act or HORTATIVE.search(n) or re.search(r"\b(aleluya|hallelujah|hosanna|gracias|thank you|amen)\b", n):
        kind = "R"
    elif sg:
        kind = "S"
    elif GOD_FOCUS.search(n):
        kind = "O"
    else:
        kind = None
    return kind, sg, pl


def analyze(lyrics, title=""):
    counts = {"O": 0, "S": 0, "R": 0}
    sg_lines = pl_lines = 0
    for line in (lyrics or "").splitlines():
        kind, sg, pl = classify_line(line)
        if kind:
            counts[kind] += 1
        sg_lines += sg
        pl_lines += pl
    if not sum(counts.values()) and title:
        # sin letra útil: se clasifica por el título
        kind, sg, pl = classify_line(title)
        if kind:
            counts[kind] += 1
        sg_lines += sg
        pl_lines += pl
    total = sum(counts.values())
    if not total:
        # sin pistas: por defecto, centrada en Dios
        return [100, 0, 0], False
    pct = [round(100 * counts[k] / total) for k in ("O", "S", "R")]
    pct[pct.index(max(pct))] += 100 - sum(pct)  # que sumen 100
    group = pl_lines >= 2 and pl_lines >= sg_lines
    return pct, group
