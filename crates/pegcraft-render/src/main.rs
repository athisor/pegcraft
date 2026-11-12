// pegcraft-render: rasteriza un fotograma horneado (escena.json v1 o v2 + SVG por dibujo) con kurbo + tiny-skia (CPU, determinista).
// v2 (integrado de <datos de trabajo omitidos>, 11-11-2026): pieza.capas (grupos <g id="underlay|colour|line|overlay"> que se dibujan) y
// pieza.recorte (cutters: cada uno multiplica la pieza por la cobertura de sus mattes, o por su complemento).
// v1 (sin `capas`): todo menos overlay, salvo --con-overlay (estado anterior).
// GLOW-SUMA (11-11-2026): pieza.mezcla = "suma" (la pone bake con --glow-suma en ramas READ -> ... -> GLOW) se SUMA al acumulado en vez de componerse con alfa. Sin el campo: identico a antes.
// Uso: pegcraft-render <escena.json> --out mio.png [--size WxH] [--bg gris|transparente] [--div N] [--sx N] [--sy N] [--sin-recorte] [--con-overlay]
use kurbo::{BezPath, PathEl};
use std::{env, fs};
use tiny_skia::*;

fn attr_f(n: &roxmltree::Node, k: &str, d: f32) -> f32 {
    n.attribute(k).and_then(|s| s.parse().ok()).unwrap_or(d)
}

fn hex(s: &str, a: f32) -> Option<Color> {
    let s = s.strip_prefix('#')?;
    if s.len() != 6 {
        return None;
    }
    let v = u32::from_str_radix(s, 16).ok()?;
    Some(Color::from_rgba8((v >> 16) as u8, (v >> 8) as u8, v as u8, (a.clamp(0.0, 1.0) * 255.0).round() as u8))
}

// matrix(a b c d e f) del SVG -> Transform de tiny-skia
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

const CAPAS: [&str; 4] = ["underlay", "colour", "line", "overlay"];

static SIN_GRADIENTES: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

// fill="url(#id)" -> shader tiny-skia. `alpha` = fill-opacity * opacidad de la pieza (multiplica el alfa de cada parada).
fn grad_shader(n: &roxmltree::Node, url: &str, alpha: f32) -> Option<Shader<'static>> {
    let id = url.strip_prefix("url(#")?.trim_end_matches(')');
    let g = n.document().descendants().find(|d| d.is_element() && d.attribute("id") == Some(id))?;
    let mut stops: Vec<GradientStop> = Vec::new();
    for s in g.children().filter(|c| c.is_element() && c.tag_name().name() == "stop") {
        let off = attr_f(&s, "offset", 0.0);
        let col = hex(s.attribute("stop-color").unwrap_or("#000000"), attr_f(&s, "stop-opacity", 1.0) * alpha)?;
        stops.push(GradientStop::new(off.clamp(0.0, 1.0), col));
    }
    let tr = g.attribute("gradientTransform").map(parse_matrix).unwrap_or(Transform::identity());
    match g.tag_name().name() {
        "linearGradient" => LinearGradient::new(
            Point::from_xy(attr_f(&g, "x1", 0.0), attr_f(&g, "y1", 0.0)),
            Point::from_xy(attr_f(&g, "x2", 1.0), attr_f(&g, "y2", 0.0)),
            stops, SpreadMode::Pad, tr),
        "radialGradient" => {
            let c = Point::from_xy(attr_f(&g, "cx", 0.5), attr_f(&g, "cy", 0.5));
            RadialGradient::new(c, 0.0, c, attr_f(&g, "r", 0.5), stops, SpreadMode::Pad, tr)
        }
        _ => None,
    }
}

// capas = None: v1 (todo menos overlay, salvo con_overlay). Some(lista): solo los grupos de arte nombrados.
fn draw_node(n: roxmltree::Node, ts: Transform, op: f32, capas: &Option<Vec<String>>, con_overlay: bool, pm: &mut PixmapMut) {
    match n.tag_name().name() {
        "g" | "svg" => {
            if let Some(id) = n.attribute("id") {
                if CAPAS.contains(&id) {
                    match capas {
                        Some(l) => {
                            if !l.iter().any(|c| c == id) {
                                return;
                            }
                        }
                        None => {
                            if id == "overlay" && !con_overlay {
                                return;
                            }
                        }
                    }
                }
            }
            let t = n.attribute("transform").map(parse_matrix).unwrap_or(Transform::identity());
            let ts2 = ts.pre_concat(t);
            for c in n.children().filter(|c| c.is_element()) {
                draw_node(c, ts2, op, capas, con_overlay, pm);
            }
        }
        "path" => {
            let Some(d) = n.attribute("d") else { return };
            let Ok(bp) = BezPath::from_svg(d) else { return };
            let Some(path) = to_path(&bp) else { return };
            let fill = n.attribute("fill").unwrap_or("none");
            if fill.starts_with("url(#") {
                // GRADIENTES (11-11-2026): <linearGradient>/<radialGradient> userSpaceOnUse + gradientTransform; paradas con alfa; SpreadMode::Pad
                if !SIN_GRADIENTES.load(std::sync::atomic::Ordering::Relaxed) {
                    if let Some(sh) = grad_shader(&n, fill, attr_f(&n, "fill-opacity", 1.0) * op) {
                        let mut p = Paint::default();
                        p.shader = sh;
                        p.anti_alias = true;
                        let rule = if n.attribute("fill-rule") == Some("evenodd") { FillRule::EvenOdd } else { FillRule::Winding };
                        pm.fill_path(&path, &p, rule, ts, None);
                    }
                }
            } else if fill != "none" {
                if let Some(c) = hex(fill, attr_f(&n, "fill-opacity", 1.0) * op) {
                    let mut p = Paint::default();
                    p.set_color(c);
                    p.anti_alias = true;
                    let rule = if n.attribute("fill-rule") == Some("evenodd") { FillRule::EvenOdd } else { FillRule::Winding };
                    pm.fill_path(&path, &p, rule, ts, None);
                }
            }
            let stroke = n.attribute("stroke").unwrap_or("none");
            if stroke != "none" {
                if let Some(c) = hex(stroke, attr_f(&n, "stroke-opacity", 1.0) * op) {
                    let mut p = Paint::default();
                    p.set_color(c);
                    p.anti_alias = true;
                    let mut st = Stroke::default();
                    st.width = attr_f(&n, "stroke-width", 1.0);
                    st.line_cap = if n.attribute("stroke-linecap") == Some("round") { LineCap::Round } else { LineCap::Butt };
                    st.line_join = if n.attribute("stroke-linejoin") == Some("round") { LineJoin::Round } else { LineJoin::Miter };
                    pm.stroke_path(&path, &p, &st, ts, None);
                }
            }
        }
        _ => {}
    }
}

// Reduccion ss:1 con gaussiano separable (sigma en px finales) sobre RGBA premultiplicado f32; muestrea en el centro del pixel final.
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

// GAUSSIANBLUR sobre el matte de un cutter (10-11-2026): desenfoca el alfa con sigma = blurriness * K px (a 1920 de ancho; K = PEGCRAFT_BLUR_K, def. 1).
fn desenfocar_matte(mk: &mut Pixmap, c: &serde_json::Value, w: u32) {
    let b = c["mattes"].as_array().unwrap().iter().filter_map(|m| m["blur"].as_f64()).fold(0.0, f64::max) as f32;
    if b <= 0.0 {
        return;
    }
    let k: f32 = std::env::var("PEGCRAFT_BLUR_K").ok().and_then(|v| v.parse().ok()).unwrap_or(1.0);
    let sg = (b * k * w as f32 / 1920.0).max(0.3);
    let (wi, hi) = (mk.width() as usize, mk.height() as usize);
    let rad = (3.0 * sg).ceil() as i64;
    let kern: Vec<f32> = (-rad..=rad).map(|i| (-((i * i) as f32) / (2.0 * sg * sg)).exp()).collect();
    let ks: f32 = kern.iter().sum();
    let d = mk.data_mut();
    let mut a: Vec<f32> = (0..wi * hi).map(|i| d[i * 4 + 3] as f32).collect();
    let mut t = vec![0f32; wi * hi];
    for y in 0..hi {
        for x in 0..wi {
            let mut acc = 0.0;
            for (j, kv) in kern.iter().enumerate() {
                let xx = x as i64 + j as i64 - rad;
                if xx >= 0 && (xx as usize) < wi {
                    acc += kv * a[y * wi + xx as usize];
                }
            }
            t[y * wi + x] = acc / ks;
        }
    }
    for y in 0..hi {
        for x in 0..wi {
            let mut acc = 0.0;
            for (j, kv) in kern.iter().enumerate() {
                let yy = y as i64 + j as i64 - rad;
                if yy >= 0 && (yy as usize) < hi {
                    acc += kv * t[yy as usize * wi + x];
                }
            }
            a[y * wi + x] = acc / ks;
        }
    }
    for i in 0..wi * hi {
        d[i * 4 + 3] = a[i].round().clamp(0.0, 255.0) as u8;
    }
}

fn capas_de(v: &serde_json::Value) -> Option<Vec<String>> {
    v.as_array().map(|a| a.iter().filter_map(|c| c.as_str().map(|s| s.to_string())).collect())
}

fn main() {
    let a: Vec<String> = env::args().collect();
    if a.len() < 2 {
        eprintln!("uso: pegcraft-render <escena.json> --out mio.png [--size WxH] [--bg gris|transparente] [--div N] [--sx N] [--sy N] [--sin-recorte] [--con-overlay]");
        std::process::exit(2);
    }
    let opt = |k: &str| a.iter().position(|x| x == k).and_then(|i| a.get(i + 1)).cloned();
    let con_overlay = a.iter().any(|x| x == "--con-overlay");
    let sin_recorte = a.iter().any(|x| x == "--sin-recorte");
    SIN_GRADIENTES.store(a.iter().any(|x| x == "--sin-gradientes"), std::sync::atomic::Ordering::Relaxed);
    let out = opt("--out").unwrap_or("mio.png".into());
    let (ow, oh) = opt("--size").and_then(|s| s.split_once('x').map(|(w, h)| (w.parse::<u32>().unwrap(), h.parse::<u32>().unwrap()))).unwrap_or((1920, 1080));
    // EXPERIMENTO bordes (11-11-2026): --aa-gauss SIGMA [--ss N] = renderiza a N x (def. 4) y reduce con un gaussiano de SIGMA px finales
    // (modelo del antialias de Harmony: cobertura filtrada por gaussiano sigma~0.45 px, lineal; (doc interna omitida). Sin el flag: igual que antes.
    let aa_gauss: Option<f32> = opt("--aa-gauss").and_then(|s| s.parse().ok());
    let ss: u32 = if aa_gauss.is_some() { opt("--ss").and_then(|s| s.parse().ok()).unwrap_or(4) } else { 1 };
    let (w, h) = (ow * ss, oh * ss);
    let opacidad_grupo = a.iter().any(|x| x == "--opacidad-grupo"); // EXPERIMENTO bordes: ver abajo
    let j: serde_json::Value = serde_json::from_str(&fs::read_to_string(&a[1]).expect("leer escena.json")).expect("json");
    let base = std::path::Path::new(&a[1]).parent().unwrap().to_path_buf();
    let cam = &j["camara"];
    let g = |k: &str, d: f64| opt(&format!("--{}", k)).and_then(|s| s.parse().ok()).unwrap_or_else(|| cam[k].as_f64().unwrap_or(d));
    let (cx, cy, sx, sy, div) = (g("cx", 960.0), g("cy", 540.0), g("sx", 60.0), g("sy", 45.06), g("div", 1.0));
    let sw = w as f64 / 1920.0; // escala si se pide otro tamano
    let mut pm = Pixmap::new(w, h).unwrap();
    if opt("--bg").as_deref() != Some("transparente") {
        pm.fill(Color::from_rgba8(128, 128, 128, 255));
    }
    let mut cache: std::collections::HashMap<String, String> = Default::default();
    // matriz_campo (2x3, campos) -> Transform a pixeles sobre coordenadas tvg (y arriba):
    // tvg (x,y) -> campo (x/div,y/div) -> M -> pixel: px = cx + sx*X ; py = cy - sy*Y
    let ts_de = |m: &serde_json::Value| -> Transform {
        let f = |r: usize, c: usize| m[r][c].as_f64().unwrap();
        let (a_, b_, tx, c_, d_, ty) = (f(0, 0) / div, f(0, 1) / div, f(0, 2), f(1, 0) / div, f(1, 1) / div, f(1, 2));
        let (kx, ky) = (sx * sw, -sy * sw);
        // el pre_concat cancela el matrix(1 0 0 -1) del SVG
        Transform::from_row((kx * a_) as f32, (ky * c_) as f32, (kx * b_) as f32, (ky * d_) as f32, ((cx + sx * tx) * sw) as f32, ((cy - sy * ty) * sw) as f32)
            .pre_concat(Transform::from_row(1.0, 0.0, 0.0, -1.0, 0.0, 0.0))
    };
    let mut dibujar = |rel: &str, ts: Transform, op: f32, capas: &Option<Vec<String>>, dst: &mut Pixmap| {
        let txt = cache.entry(rel.to_string()).or_insert_with(|| fs::read_to_string(base.join(rel)).expect("svg"));
        let doc = roxmltree::Document::parse(txt).expect("xml");
        draw_node(doc.root_element(), ts, op, capas, con_overlay, &mut dst.as_mut());
    };
    let (mut n, mut nrec, mut nsuma) = (0, 0, 0);
    for p in j["piezas"].as_array().unwrap() {
        let ts = ts_de(&p["matriz_campo"]);
        let rel = p["dibujo"].as_str().unwrap().to_string();
        let op = p["opacidad"].as_f64().unwrap_or(1.0) as f32;
        let capas = capas_de(&p["capas"]);
        let cortes: Vec<&serde_json::Value> = p["recorte"].as_array().map(|v| v.iter().collect()).unwrap_or_default();
        // v1 guardaba mattes como lista de ids (sin dibujo): solo recortan los que traen objetos {dibujo, matriz_campo, capas}
        let cortes: Vec<&serde_json::Value> = cortes
            .into_iter()
            .filter(|c| c["mattes"].as_array().map(|v| v.iter().all(|m| m.is_object())).unwrap_or(false))
            .collect();
        if p["mezcla"].as_str() == Some("suma") {
            // GLOW-SUMA (11-11-2026): la pieza (con su opacidad y sus cutters) se dibuja a un lienzo propio y se SUMA por canal
            // al acumulado (premultiplicado: dst.rgb += src.rgb, saturado al alfa resultante). Harmony: READ -> CUTTER -> GLOW -> COMPOSITE.
            let mut tmp = Pixmap::new(w, h).unwrap();
            if opacidad_grupo && op < 1.0 {
                dibujar(&rel, ts, 1.0, &capas, &mut tmp);
                let k = (op.clamp(0.0, 1.0) * 256.0) as u32;
                for v in tmp.data_mut().iter_mut() {
                    *v = ((*v as u32 * k) >> 8) as u8;
                }
            } else {
                dibujar(&rel, ts, op, &capas, &mut tmp);
            }
            if !sin_recorte {
                for c in &cortes {
                    let mut mk = Pixmap::new(w, h).unwrap();
                    for m in c["mattes"].as_array().unwrap() {
                        dibujar(m["dibujo"].as_str().unwrap(), ts_de(&m["matriz_campo"]), 1.0, &capas_de(&m["capas"]), &mut mk);
                    }
                    desenfocar_matte(&mut mk, c, w);
                    let inv = c["invertido"].as_bool().unwrap_or(false);
                    let md = mk.data();
                    let td = tmp.data_mut();
                    for i in 0..(w * h) as usize {
                        let ma = md[i * 4 + 3] as u32;
                        let k = if inv { ma } else { 255 - ma };
                        if k < 255 {
                            for ch in 0..4 {
                                td[i * 4 + ch] = ((td[i * 4 + ch] as u32 * k + 127) / 255) as u8;
                            }
                        }
                    }
                }
            }
            let gan = p["ganancia"].as_f64().unwrap_or(1.0).clamp(0.0, 8.0) as f32;
            if gan != 1.0 {
                let k = (gan * 256.0) as u32;
                for v in tmp.data_mut().iter_mut() {
                    *v = ((*v as u32 * k) >> 8).min(255) as u8;
                }
            }
            let sd = tmp.data();
            let dd = pm.data_mut();
            for i in 0..(w * h) as usize {
                let sa = sd[i * 4 + 3] as u32;
                if sa == 0 {
                    continue;
                }
                let da = dd[i * 4 + 3] as u32;
                let oa = sa + da - (sa * da + 127) / 255; // union de alfas
                for ch in 0..3 {
                    dd[i * 4 + ch] = (dd[i * 4 + ch] as u32 + sd[i * 4 + ch] as u32).min(oa) as u8;
                }
                dd[i * 4 + 3] = oa as u8;
            }
            nsuma += 1;
        } else if (cortes.is_empty() || sin_recorte) && opacidad_grupo && op < 1.0 {
            // EXPERIMENTO bordes: opacidad de la pieza aplicada UNA vez al dibujo ya aplanado (union), no por path
            let mut tmp = Pixmap::new(w, h).unwrap();
            dibujar(&rel, ts, 1.0, &capas, &mut tmp);
            let mut pp = PixmapPaint::default();
            pp.opacity = op;
            pm.draw_pixmap(0, 0, tmp.as_ref(), &pp, Transform::identity(), None);
        } else if cortes.is_empty() || sin_recorte {
            dibujar(&rel, ts, op, &capas, &mut pm);
        } else {
            // pieza a un lienzo propio; cada cutter multiplica su alfa por la cobertura del matte (o su complemento)
            let mut tmp = Pixmap::new(w, h).unwrap();
            dibujar(&rel, ts, op, &capas, &mut tmp);
            for c in cortes {
                let mut mk = Pixmap::new(w, h).unwrap();
                for m in c["mattes"].as_array().unwrap() {
                    dibujar(m["dibujo"].as_str().unwrap(), ts_de(&m["matriz_campo"]), 1.0, &capas_de(&m["capas"]), &mut mk);
                }
                desenfocar_matte(&mut mk, c, w);
                let inv = c["invertido"].as_bool().unwrap_or(false);
                let md = mk.data();
                let td = tmp.data_mut();
                for i in 0..(w * h) as usize {
                    let ma = md[i * 4 + 3] as u32;
                    let k = if inv { ma } else { 255 - ma }; // normal: se borra donde hay matte; invertido: queda solo dentro
                    if k < 255 {
                        for ch in 0..4 {
                            td[i * 4 + ch] = ((td[i * 4 + ch] as u32 * k + 127) / 255) as u8;
                        }
                    }
                }
            }
            pm.draw_pixmap(0, 0, tmp.as_ref(), &PixmapPaint::default(), Transform::identity(), None);
            nrec += 1;
        }
        n += 1;
    }
    if let Some(sg) = aa_gauss {
        pm = reducir_gauss(&pm, ss, sg, ow, oh);
    }
    pm.save_png(&out).expect("png");
    if nsuma > 0 {
        eprintln!("{} piezas ({} con recorte, {} en suma) -> {} ({}x{})", n, nrec, nsuma, out, w, h);
    } else {
        eprintln!("{} piezas ({} con recorte) -> {} ({}x{})", n, nrec, out, w, h);
    }
}
