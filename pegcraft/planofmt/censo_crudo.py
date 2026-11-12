"""Censo CRUDO de un .xstage (ElementTree, sin pasar por sightread.lector): tipos de nodo, atributos de <attrs> con su valor por omision,
cuantos nodos los llevan, cuantos con valor distinto del default, cuantos ligados a columna; columnas, claves, options/metrics.

  python -m pegcraft.planofmt.censo_crudo <xstage> [--json salida.json] [--max N]

Salida acotada: una linea por (tipo de nodo, atributo). Solo lectura.
"""
import sys, json, argparse, collections
import xml.etree.ElementTree as ET


def _num(s):
    try: return float(s)
    except Exception: return s


def _distinto(val, dflt):
    if dflt is None: return None
    a, b = _num(val), _num(dflt)
    if isinstance(a, float) and isinstance(b, float): return abs(a - b) > 1e-9
    return a != b


def _hojas(el, pref, out):
    """(ruta, val, defaultValue, col) de cada hoja con atributo val bajo <attrs>."""
    for ch in el:
        r = f"{pref}/{ch.tag}" if pref else ch.tag
        if "val" in ch.attrib:
            out.append((r, ch.get("val"), ch.get("defaultValue"), ch.get("col")))
        _hojas(ch, r, out)


def censo(path):
    root = ET.parse(path).getroot()
    C = {"archivo": str(path), "tipos": collections.Counter(), "attrs": {}, "options": {}, "columnas": collections.Counter(),
         "pt": collections.Counter(), "metrics": {}, "otros_hijos_de_scene": collections.Counter(), "apagados": collections.Counter(),
         "col_ligadas": collections.Counter()}
    for sc in root.iter("scene"):
        for ch in sc: C["otros_hijos_de_scene"][ch.tag] += 1
    for m in root.iter("metrics"): C["metrics"] = dict(m.attrib)
    for c in root.iter("column"): C["columnas"][c.get("type")] += 1
    for p in root.iter("pt"): C["pt"][tuple(sorted(p.attrib))] += 1
    for mod in root.iter("module"):
        t = mod.get("type"); C["tipos"][t] += 1
        op = mod.find("options")
        if op is not None:
            for o in op:
                if o.tag == "disabled" and o.get("val") == "true": C["apagados"][t] += 1
                k = f"{t}|options/{o.tag}"; C["options"][k] = C["options"].get(k, 0) + 1
        at = mod.find("attrs")
        if at is None: continue
        hs = []; _hojas(at, "", hs)
        for r, v, d, col in hs:
            e = C["attrs"].setdefault(f"{t}|{r}", {"n": 0, "no_default": 0, "con_columna": 0, "valores": collections.Counter(), "default": d})
            e["n"] += 1
            if _distinto(v, d): e["no_default"] += 1
            if col: e["con_columna"] += 1
            if len(e["valores"]) < 6: e["valores"][v] += 1
    return C


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("xstage"); ap.add_argument("--json"); ap.add_argument("--max", type=int, default=400)
    a = ap.parse_args(argv)
    C = censo(a.xstage)
    print("tipos:", dict(C["tipos"].most_common())); print("columnas:", dict(C["columnas"])); print("metrics:", C["metrics"])
    print("apagados:", dict(C["apagados"])); print("pt:", {",".join(k): v for k, v in C["pt"].items()})
    for i, (k, e) in enumerate(sorted(C["attrs"].items(), key=lambda kv: (-kv[1]["no_default"], kv[0]))):
        if i >= a.max: break
        print(f"{k}  n={e['n']} no_default={e['no_default']} col={e['con_columna']} def={e['default']} v={dict(e['valores'])}")
    if a.json:
        C["attrs"] = {k: {**e, "valores": dict(e["valores"])} for k, e in C["attrs"].items()}
        C["tipos"] = dict(C["tipos"]); C["columnas"] = dict(C["columnas"]); C["pt"] = {",".join(k): v for k, v in C["pt"].items()}
        C["otros_hijos_de_scene"] = dict(C["otros_hijos_de_scene"]); C["apagados"] = dict(C["apagados"]); C.pop("col_ligadas")
        json.dump(C, open(a.json, "w", encoding="utf-8"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
