"""
Parse the five PVC index data-bank PDFs into clean monthly series.

Each series is a dict keyed "YYYY-MM" -> float:
  labour          CPI-IW general index (base 2016=100)
  machinery       WPI machinery sub-group (base 2011-12)
  material        WPI all commodities   (base 2011-12)
  diesel          PPAC retail diesel, all-metro average
  tmt             JPC TMT bar rate (Rs/tonne)
  steel_other     JPC "other categories" steel = mean(TMT, angle, plate)

These feed the GCC 46A PVC calculation in pvc.py.
"""
import re
import pdfplumber

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "june": 6,
           "jul": 7, "july": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10,
           "nov": 11, "dec": 12}
_NUM = re.compile(r"-?\d[\d,]*\.?\d*")


def _key(year, month):
    return f"{int(year):04d}-{int(month):02d}"


def _nums(line):
    return [float(x.replace(",", "")) for x in _NUM.findall(line)]


def _text(path):
    out = []
    with pdfplumber.open(path) as pdf:
        for p in pdf.pages:
            out.append(p.extract_text() or "")
    return "\n".join(out)


def parse_matrix(path, year_min=2018, year_max=2030):
    """WPI-style: a '<year> v1 v2 ... v12' line, values in Jan..Dec order."""
    series = {}
    for line in _text(path).split("\n"):
        toks = line.split()
        if not toks:
            continue
        m = re.fullmatch(r"(20\d\d)", toks[0])
        if not m:
            continue
        year = int(toks[0])
        if not (year_min <= year <= year_max):
            continue
        vals = _nums(line)[1:]  # drop the year itself
        for i, v in enumerate(vals[:12]):
            series[_key(year, i + 1)] = v
    return series


def parse_labour(path):
    """CPI-IW: take only the (Base 2016=100) section; the year sits on the
    line immediately before each 'General Index v1..vN' line."""
    series = {}
    prev = ""
    for line in _text(path).split("\n"):
        if "Base 2001" in line:           # stop before the 2001-base section
            break
        if line.strip().startswith("General Index"):
            ym = re.search(r"(20\d\d)", prev)
            if ym:
                year = int(ym.group(1))
                vals = _nums(line)
                for i, v in enumerate(vals[:12]):
                    series[_key(year, i + 1)] = v
        prev = line
    return series


def parse_diesel(path):
    """PPAC: 'Mon-YY d m c k AVG' -> take the average (last value)."""
    series = {}
    for line in _text(path).split("\n"):
        m = re.match(r"\s*([A-Za-z]+)-(\d{2})\b", line)
        if not m:
            continue
        mon = _MONTHS.get(m.group(1).lower())
        if not mon:
            continue
        year = 2000 + int(m.group(2))
        vals = _nums(line.split("-", 1)[1])  # numbers after the month token
        if vals:
            series[_key(year, mon)] = vals[-1]   # average column
    return series


def parse_steel(path):
    """JPC: tmt = first rate; other-categories = mean(tmt, angle, plate).

    Two layouts appear: aligned ('Mon-YY r1 r2 r3 r4') and, on later pages,
    wrapped (a bare rates line followed by the 'Mon-YY' label on the next line).
    """
    tmt, other = {}, {}
    pending = None  # a rates line still waiting for its month label below it
    for line in _text(path).split("\n"):
        s = line.strip()
        m = re.match(r"([A-Za-z]{3,4})-(\d{2})\b", s)
        if m:
            mon = _MONTHS.get(m.group(1).lower())
            year = 2000 + int(m.group(2))
            if mon:
                k = _key(year, mon)
                inline = [v for v in _nums(s.split("-", 1)[1]) if v > 1000]
                if len(inline) >= 3:
                    tmt[k] = inline[0]
                    other[k] = round(sum(inline[:3]) / 3, 2)
                    pending = None
                elif pending and len(pending) >= 3:
                    tmt[k] = pending[0]
                    other[k] = round(sum(pending[:3]) / 3, 2)
                    pending = None
            continue
        rates = [v for v in _nums(s) if v > 1000]
        if len(rates) >= 3:
            pending = rates
    return tmt, other


def load_all(paths):
    """paths: dict with keys labour, machinery, material, diesel, steel."""
    tmt, steel_other = parse_steel(paths["steel"])
    return {
        "labour": parse_labour(paths["labour"]),
        "machinery": parse_matrix(paths["machinery"]),
        "material": parse_matrix(paths["material"]),
        "diesel": parse_diesel(paths["diesel"]),
        "tmt": tmt,
        "steel_other": steel_other,
    }
