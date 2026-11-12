// Rasterizado de escenas horneadas para el visor.
// ATRIBUCION: la logica (conversion matriz_campo -> pixeles, capas underlay/colour/line/overlay, cutters como multiplicacion por la
// cobertura del matte, opacidad de grupo, reduccion gaussiana de --aa-gauss 0.45 --ss 2) es una adaptacion de
// ../pegcraft-render/src/main.rs (mismo repo, sin modificarlo). Diferencia: los SVG se parsean UNA vez a primitivas (cache) para que
// re-renderizar tras apagar una capa o editar un parametro sea barato.
use kurbo::{BezPath, PathEl};
use std::{collections::HashMap, collections::HashSet, fs, path::PathBuf, rc::Rc};
use tiny_skia::*;

pub const CAPAS: [&str; 4] = ["underlay", "colour", "line", "overlay"];

pub struct Prim {
    pub path: Path,
    pub fill: Option<([u8; 3], f32, bool)>, // rgb, alfa, evenodd
    pub stroke: Option<([u8; 3], f32, f32, bool, bool)>, // rgb, alfa, ancho, cap redondo, join redondo
    pub t: Transform,
    pub capa: Option<&'static str>,
}
pub struct Dibujo {
    pub prims: Vec<Prim>,
}

fn attr_f(n: &roxmltree::Node, k: &str, d: f32) -> f32 {
    n.attribute(k).and_then(|s| s.parse().ok()).unwrap_or(d)
}
fn hex(s: &str) -> Option<[u8; 3]> {
    let s = s.strip_prefix('#')?;
    if s.len() != 6 {
        return None;
    }
    let v = u32::from_str_radix(s, 16).ok()?;
    Some([(v >> 16) as u8, (v >> 8) as u8, v as u8])
}
fn parse_matrix(s: &str) -> Transform {
    let inner = s.trim().trim_start_matches("matrix(").trim_end_matches(')');
    let v: Vec<f32> = inner.split(|c: char| c == ' ' || c == ',').filter(|t| !t.is_empty()).filter_map(|t| t.parse().ok()).collect();
    if v.len() == 6 { Transform::from_row(v[0], v[1], v[2], v[3], v[4], v[5]) } else { Transform::identity() }
}
fn to_path(bp: &BezPath) -> Option<Path> {
    let mut pb = PathBuilder::new();
    for el in bp.elements() {
        match *el {
            PathEl::MoveTo(p) => pb.move_to(p.x as f32, p.y as f32),
            PathEl::LineTo(p) => pb.line_to(p.x as f32, p.y as f32),
            PathEl::QuadTo(a, p) => pb.quad_to(a.x as f32, a.y as f32, p.x as f32, p.y as f32),
            PathEl::CurveTo(a, b, p) => pb.cubic_to(a.x as f32, a.y as f32, b.x as f32, b.y as f32, p.x as f32, p.y as f32),
            PathEl::ClosePath => pb.close(),
        }
    }
    pb.finish()
}
fn recoge(n: roxmltree::Node, t: Transform, capa: Option<&'static str>, out: &mut Vec<Prim>) {
    match n.tag_name().name() {
        "g" | "svg" => {
            let mut capa = capa;
            if let Some(id) = n.attribute("id") {
                if let Some(c) = CAPAS.iter().find(|c| **c == id) {
                    capa = Some(c);
                }
            }
            let t2 = t.pre_concat(n.attribute("transform").map(parse_matrix).unwrap_or(Transform::identity()));
            for c in n.children().filter(|c| c.is_element()) {
                recoge(c, t2, capa, out);
            }
        }
        "path" => {
            let Some(d) = n.attribute("d") else { return };
            let Ok(bp) = BezPath::from_svg(d) else { return };
            let Some(path) = to_path(&bp) else { return };
            let fill = n.attribute("fill").filter(|f| *f != "none").and_then(hex).map(|c| (c, attr_f(&n, "fill-opacity", 1.0), n.attribute("fill-rule") == Some("evenodd")));
            let stroke = n.attribute("stroke").filter(|f| *f != "none").and_then(hex).map(|c| {
                (c, attr_f(&n, "stroke-opacity", 1.0), attr_f(&n, "stroke-width", 1.0), n.attribute("stroke-linecap") == Some("round"), n.attribute("stroke-linejoin") == Some("round"))
            });
            if fill.is_some() || stroke.is_some() {
                out.push(Prim { path, fill, stroke, t, capa });
            }
        }
        _ => {}
    }
}

#[derive(Default)]
pub struct Cache {
    pub dibujos: HashMap<PathBuf, Option<Rc<Dibujo>>>,
}
impl Cache {
    pub fn dibujo(&mut self, p: PathBuf) -> Option<Rc<Dibujo>> {
        self.dibujos
            .entry(p.clone())
            .or_insert_with(|| {
                let txt = fs::read_to_string(&p).ok()?;
                let doc = roxmltree::Document::parse(&txt).ok()?;
                let mut prims = vec![];
                recoge(doc.root_element(), Transform::identity(), None, &mut prims);
                Some(Rc::new(Dibujo { prims }))
            })
            .clone()
    }
}

pub type M = [[f64; 3]; 2];
pub struct Matte {
    pub dibujo: String,
    pub m: M,
    pub capas: Option<Vec<String>>,
}
pub struct Corte {
    pub inv: bool,
    pub mattes: Vec<Matte>,
    pub nodo: String,
}
pub struct Pieza {
    pub id: String,
    pub key: String, // id + puertos: identifica la instancia entre fotogramas
    pub orden: i64,
    pub razon: String,
    pub puertos: Vec<i64>,
    pub z: f64,
    pub dibujo: String,
    pub m: M,
    pub capas: Option<Vec<String>>,
    pub recorte: Vec<Corte>,
    pub opacidad: f32,
}
pub struct Escena {
    pub nombre: String,
    pub fotograma: i64,
    pub tam: (u32, u32),
    pub cam: (f64, f64, f64, f64, f64), // cx cy sx sy div
    pub base: PathBuf,
    pub piezas: Vec<Pieza>,
}

fn mat(v: &serde_json::Value) -> M {
    let f = |r: usize, c: usize| v[r][c].as_f64().unwrap_or(if r == c { 1.0 } else { 0.0 });
    [[f(0, 0), f(0, 1), f(0, 2)], [f(1, 0), f(1, 1), f(1, 2)]]
}
fn capas_de(v: &serde_json::Value) -> Option<Vec<String>> {
    v.as_array().map(|a| a.iter().filter_map(|c| c.as_str().map(|s| s.to_string())).collect())
}

pub fn cargar(ruta: &std::path::Path) -> Result<Escena, String> {
    let j: serde_json::Value = serde_json::from_str(&fs::read_to_string(ruta).map_err(|e| format!("{ruta:?}: {e}"))?).map_err(|e| e.to_string())?;
    let cam = &j["camara"];
    let g = |k: &str, d: f64| cam[k].as_f64().unwrap_or(d);
    let mut piezas = vec![];
    for p in j["piezas"].as_array().ok_or("sin piezas")? {
        let puertos: Vec<i64> = p["puertos"].as_array().map(|a| a.iter().filter_map(|x| x.as_i64()).collect()).unwrap_or_default();
        let id = p["id"].as_str().unwrap_or("?").to_string();
        let key = format!("{id}@{}", puertos.iter().map(|x| x.to_string()).collect::<Vec<_>>().join("."));
        let recorte = p["recorte"]
            .as_array()
            .map(|v| {
                v.iter()
                    .filter(|c| c["mattes"].as_array().map(|m| m.iter().all(|x| x.is_object())).unwrap_or(false))
                    .map(|c| Corte {
                        inv: c["invertido"].as_bool().unwrap_or(false),
                        nodo: c["nodo"].as_str().unwrap_or("").to_string(),
                        mattes: c["mattes"]
                            .as_array()
                            .unwrap()
                            .iter()
                            .map(|m| Matte { dibujo: m["dibujo"].as_str().unwrap_or("").to_string(), m: mat(&m["matriz_campo"]), capas: capas_de(&m["capas"]) })
                            .collect(),
                    })
                    .collect()
            })
            .unwrap_or_default();
        piezas.push(Pieza {
            id,
            key,
            orden: p["orden"].as_i64().unwrap_or(0),
            razon: p["razon"].as_str().unwrap_or("").to_string(),
            puertos,
            z: p["z"].as_f64().unwrap_or(0.0),
            dibujo: p["dibujo"].as_str().unwrap_or("").to_string(),
            m: mat(&p["matriz_campo"]),
            capas: capas_de(&p["capas"]),
            recorte,
            opacidad: p["opacidad"].as_f64().unwrap_or(1.0) as f32,
        });
    }
    Ok(Escena {
        nombre: j["escena"].as_str().unwrap_or("").to_string(),
        fotograma: j["fotograma"].as_i64().unwrap_or(0),
        tam: (j["tamano"][0].as_u64().unwrap_or(1920) as u32, j["tamano"][1].as_u64().unwrap_or(1080) as u32),
        cam: (g("cx", 960.0), g("cy", 540.0), g("sx", 60.0), g("sy", 45.06), g("div", 1.0)),
        base: ruta.parent().unwrap().to_path_buf(),
        piezas,
    })
}

#[derive(Clone, Copy, PartialEq, Debug)]
pub struct Edit {
    pub dx: f32,
    pub dy: f32,
    pub rot: f32, // grados, antihorario
    pub esc: f32,
    pub escy: f32,
    pub op: f32,
}
impl Default for Edit {
    fn default() -> Self {
        Edit { dx: 0.0, dy: 0.0, rot: 0.0, esc: 1.0, escy: 1.0, op: 1.0 }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub enum Calidad {
    Rapida, // 1/2, AA directo
    Completa, // 1x, AA directo
    Exacta, // 1x, ss 2 + gauss 0.45 (modo que coincide 99,6 % con Harmony)
}
impl Calidad {
    pub fn ss(self) -> u32 {
        if self == Calidad::Exacta { 2 } else { 1 }
    }
    pub fn out(self, t: (u32, u32)) -> (u32, u32) {
        if self == Calidad::Rapida { (t.0 / 2, t.1 / 2) } else { t }
    }
}

#[derive(Default)]
pub struct Estado {
    pub ocultas: HashSet<String>,
    pub ediciones: HashMap<String, Edit>,
}

/// matriz de campos (+ edicion) -> transform sobre coordenadas tvg (y arriba), en pixeles del lienzo de trabajo
fn ts_de(e: &Escena, m: &M, ed: Option<&Edit>, w: u32) -> Transform {
    let (cx, cy, sx, sy, div) = e.cam;
    let sw = w as f64 / 1920.0;
    let (mut a, mut b, mut tx, mut c, mut d, mut ty) = (m[0][0], m[0][1], m[0][2], m[1][0], m[1][1], m[1][2]);
    if let Some(ed) = ed {
        // rotacion y escala LOCALES (sobre el origen de la pieza), traslacion en campos
        let (s, co) = (ed.rot as f64).to_radians().sin_cos();
        let (kx, ky) = (ed.esc as f64, ed.escy as f64);
        let (r00, r01, r10, r11) = (co * kx, -s * ky, s * kx, co * ky);
        let (na, nb, nc, nd) = (a * r00 + b * r10, a * r01 + b * r11, c * r00 + d * r10, c * r01 + d * r11);
        a = na;
        b = nb;
        c = nc;
        d = nd;
        tx += ed.dx as f64;
        ty += ed.dy as f64;
    }
    let (a_, b_, c_, d_) = (a / div, b / div, c / div, d / div);
    let (kx, ky) = (sx * sw, -sy * sw);
    Transform::from_row((kx * a_) as f32, (ky * c_) as f32, (kx * b_) as f32, (ky * d_) as f32, ((cx + sx * tx) * sw) as f32, ((cy - sy * ty) * sw) as f32)
        .pre_concat(Transform::from_row(1.0, 0.0, 0.0, -1.0, 0.0, 0.0))
}

fn permitida(p: &Prim, capas: &Option<Vec<String>>) -> bool {
    match (p.capa, capas) {
        (None, _) => true,
        (Some(c), Some(l)) => l.iter().any(|x| x == c),
        (Some(c), None) => c != "overlay",
    }
}
fn dibuja(d: &Dibujo, ts: Transform, op: f32, capas: &Option<Vec<String>>, pm: &mut PixmapMut) {
    for p in d.prims.iter().filter(|p| permitida(p, capas)) {
        let t = ts.pre_concat(p.t);
        if let Some((c, a, eo)) = p.fill {
            let mut pt = Paint::default();
            pt.set_color(Color::from_rgba8(c[0], c[1], c[2], ((a * op).clamp(0.0, 1.0) * 255.0).round() as u8));
            pt.anti_alias = true;
            pm.fill_path(&p.path, &pt, if eo { FillRule::EvenOdd } else { FillRule::Winding }, t, None);
        }
        if let Some((c, a, w, cap, join)) = p.stroke {
            let mut pt = Paint::default();
            pt.set_color(Color::from_rgba8(c[0], c[1], c[2], ((a * op).clamp(0.0, 1.0) * 255.0).round() as u8));
            pt.anti_alias = true;
            let mut st = Stroke::default();
            st.width = w;
            st.line_cap = if cap { LineCap::Round } else { LineCap::Butt };
            st.line_join = if join { LineJoin::Round } else { LineJoin::Miter };
            pm.stroke_path(&p.path, &pt, &st, t, None);
        }
    }
}

fn reducir_gauss(src: &Pixmap, ss: u32, sigma: f32, ow: u32, oh: u32) -> Pixmap {
    let (w, h) = (src.width() as usize, src.height() as usize);
    let (ow, oh, ss) = (ow as usize, oh as usize, ss as usize);
    let s = (sigma * ss as f32).max(1e-3);
    let rad = (3.0 * s).ceil() as i64;
    let kern = |c: f32| -> Vec<(i64, f32)> {
        let c0 = c.round() as i64;
        let mut v: Vec<(i64, f32)> = (c0 - rad..=c0 + rad).map(|i| (i, (-((i as f32 - c).powi(2)) / (2.0 * s * s)).exp())).collect();
        let t: f32 = v.iter().map(|x| x.1).sum();
        v.iter_mut().for_each(|x| x.1 /= t);
        v
    };
    let d = src.data();
    let mut tmp = vec![0f32; ow * h * 4];
    for ox in 0..ow {
        let k = kern(ox as f32 * ss as f32 + (ss as f32 - 1.0) / 2.0);
        for y in 0..h {
            let mut acc = [0f32; 4];
            for &(i, wt) in &k {
                let x = i.clamp(0, w as i64 - 1) as usize;
                for ch in 0..4 {
                    acc[ch] += d[(y * w + x) * 4 + ch] as f32 * wt;
                }
            }
            for ch in 0..4 {
                tmp[(y * ow + ox) * 4 + ch] = acc[ch];
            }
        }
    }
    let mut out = Pixmap::new(ow as u32, oh as u32).unwrap();
    let od = out.data_mut();
    for oy in 0..oh {
        let k = kern(oy as f32 * ss as f32 + (ss as f32 - 1.0) / 2.0);
        for x in 0..ow {
            let mut acc = [0f32; 4];
            for &(i, wt) in &k {
                let y = i.clamp(0, h as i64 - 1) as usize;
                for ch in 0..4 {
                    acc[ch] += tmp[(y * ow + x) * 4 + ch] * wt;
                }
            }
            let a = (acc[3] + 0.5).floor().clamp(0.0, 255.0);
            for ch in 0..3 {
                od[(oy * ow + x) * 4 + ch] = (acc[ch] + 0.5).floor().clamp(0.0, a) as u8;
            }
            od[(oy * ow + x) * 4 + 3] = a as u8;
        }
    }
    out
}

pub fn render(e: &Escena, cache: &mut Cache, st: &Estado, q: Calidad) -> Pixmap {
    let (ow, oh) = q.out(e.tam);
    let ss = q.ss();
    let (w, h) = (ow * ss, oh * ss);
    let mut pm = Pixmap::new(w, h).unwrap();
    pm.fill(Color::from_rgba8(128, 128, 128, 255));
    for p in &e.piezas {
        if st.ocultas.contains(&p.key) {
            continue;
        }
        let ed = st.ediciones.get(&p.key);
        let op = p.opacidad * ed.map(|x| x.op).unwrap_or(1.0);
        let Some(d) = cache.dibujo(e.base.join(&p.dibujo)) else { continue };
        let ts = ts_de(e, &p.m, ed, w);
        let mut pp = PixmapPaint::default();
        pp.opacity = op;
        if p.recorte.is_empty() {
            if op >= 0.999 {
                dibuja(&d, ts, 1.0, &p.capas, &mut pm.as_mut());
            } else {
                let mut tmp = Pixmap::new(w, h).unwrap();
                dibuja(&d, ts, 1.0, &p.capas, &mut tmp.as_mut());
                pm.draw_pixmap(0, 0, tmp.as_ref(), &pp, Transform::identity(), None);
            }
        } else {
            let mut tmp = Pixmap::new(w, h).unwrap();
            dibuja(&d, ts, 1.0, &p.capas, &mut tmp.as_mut());
            for c in &p.recorte {
                let mut mk = Pixmap::new(w, h).unwrap();
                for m in &c.mattes {
                    if let Some(md) = cache.dibujo(e.base.join(&m.dibujo)) {
                        dibuja(&md, ts_de(e, &m.m, None, w), 1.0, &m.capas, &mut mk.as_mut());
                    }
                }
                let md = mk.data();
                let td = tmp.data_mut();
                for i in 0..(w * h) as usize {
                    let ma = md[i * 4 + 3] as u32;
                    let k = if c.inv { ma } else { 255 - ma };
                    if k < 255 {
                        for ch in 0..4 {
                            td[i * 4 + ch] = ((td[i * 4 + ch] as u32 * k + 127) / 255) as u8;
                        }
                    }
                }
            }
            pm.draw_pixmap(0, 0, tmp.as_ref(), &pp, Transform::identity(), None);
        }
    }
    if ss > 1 { reducir_gauss(&pm, ss, 0.45, ow, oh) } else { pm }
}

/// caja de una pieza en fracciones del cuadro (0..1), o None si no tiene geometria
pub fn caja(e: &Escena, cache: &mut Cache, idx: usize, st: &Estado) -> Option<[f32; 4]> {
    let p = e.piezas.get(idx)?;
    let d = cache.dibujo(e.base.join(&p.dibujo))?;
    let w = 1920u32;
    let ts = ts_de(e, &p.m, st.ediciones.get(&p.key), w);
    let (mut x0, mut y0, mut x1, mut y1) = (f32::MAX, f32::MAX, f32::MIN, f32::MIN);
    for pr in d.prims.iter().filter(|q| permitida(q, &p.capas)) {
        let b = pr.path.bounds();
        let t = ts.pre_concat(pr.t);
        for (x, y) in [(b.left(), b.top()), (b.right(), b.top()), (b.left(), b.bottom()), (b.right(), b.bottom())] {
            let (px, py) = (t.sx * x + t.kx * y + t.tx, t.ky * x + t.sy * y + t.ty);
            x0 = x0.min(px);
            y0 = y0.min(py);
            x1 = x1.max(px);
            y1 = y1.max(py);
        }
    }
    if x0 > x1 {
        return None;
    }
    let (fw, fh) = (e.tam.0 as f32, e.tam.1 as f32);
    Some([x0 / fw, y0 / fh, x1 / fw, y1 / fh])
}
