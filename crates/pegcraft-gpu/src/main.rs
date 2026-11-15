// pegcraft-gpu: SPIKE. Lee el mismo escena.json v2 + dibujos\*.svg que pegcraft-render (CPU, kurbo + tiny-skia) y lo dibuja con
// vello (wgpu). La logica de parseo (matriz de pieza, capas, opacidad, gradientes, cutters) esta copiada de
// crates\pegcraft-render\src\main.rs (atribucion interna; el crate CPU no se toca).
// Uso: pegcraft-gpu <escena.json> --out png [--size WxH] [--ss N] [--aa-gauss S] [--repetir N] [--opacidad-grupo] [--sin-recorte]
//      [--sin-gradientes] [--con-overlay] [--bg gris|transparente]
use std::{collections::HashMap, env, fs, time::Instant};
use vello::kurbo::{Affine, BezPath, Cap, Join, Point, Rect, Shape, Stroke};
use vello::peniko::{BlendMode, Brush, Color, Compose, Fill, Gradient, Mix};
use vello::{wgpu, Scene};

const CAPAS: [&str; 4] = ["underlay", "colour", "line", "overlay"];

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
fn a8(a: f32) -> u8 {
    (a.clamp(0.0, 1.0) * 255.0).round() as u8
}
fn parse_matrix(s: &str) -> Affine {
    let inner = s.trim().trim_start_matches("matrix(").trim_end_matches(')');
    let v: Vec<f64> = inner.split(|c: char| c == ' ' || c == ',').filter(|t| !t.is_empty()).filter_map(|t| t.parse().ok()).collect();
    if v.len() == 6 { Affine::new([v[0], v[1], v[2], v[3], v[4], v[5]]) } else { Affine::IDENTITY }
}

#[derive(Clone)]
enum Relleno {
    Solido([u8; 3], f32),
    Lineal { p1: Point, p2: Point, stops: Vec<(f32, [u8; 3], f32)>, tr: Affine, fo: f32 },
    Radial { c: Point, r: f32, stops: Vec<(f32, [u8; 3], f32)>, tr: Affine, fo: f32 },
}
struct Trazo {
    col: [u8; 3],
    a: f32,
    w: f64,
    redondo_cap: bool,
    redondo_join: bool,
}
struct Item {
    path: BezPath,
    ts: Affine,
    evenodd: bool,
    relleno: Option<Relleno>,
    trazo: Option<Trazo>,
}

fn grad_de(n: &roxmltree::Node, url: &str, fo: f32) -> Option<Relleno> {
    let id = url.strip_prefix("url(#")?.trim_end_matches(')');
    let g = n.document().descendants().find(|d| d.is_element() && d.attribute("id") == Some(id))?;
    let mut stops = Vec::new();
    for s in g.children().filter(|c| c.is_element() && c.tag_name().name() == "stop") {
        let off = attr_f(&s, "offset", 0.0).clamp(0.0, 1.0);
        let col = hex(s.attribute("stop-color").unwrap_or("#000000"))?;
        stops.push((off, col, attr_f(&s, "stop-opacity", 1.0)));
    }
    let tr = g.attribute("gradientTransform").map(parse_matrix).unwrap_or(Affine::IDENTITY);
    match g.tag_name().name() {
        "linearGradient" => Some(Relleno::Lineal {
            p1: Point::new(attr_f(&g, "x1", 0.0) as f64, attr_f(&g, "y1", 0.0) as f64),
            p2: Point::new(attr_f(&g, "x2", 1.0) as f64, attr_f(&g, "y2", 0.0) as f64),
            stops, tr, fo,
        }),
        "radialGradient" => Some(Relleno::Radial {
            c: Point::new(attr_f(&g, "cx", 0.5) as f64, attr_f(&g, "cy", 0.5) as f64),
            r: attr_f(&g, "r", 0.5), stops, tr, fo,
        }),
        _ => None,
    }
}

// Aplana un SVG a una lista de items (independiente de la pieza); misma logica de capas que draw_node del crate CPU.
fn aplanar(n: roxmltree::Node, ts: Affine, capas: &Option<Vec<String>>, con_overlay: bool, sin_grad: bool, out: &mut Vec<Item>) {
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
            let t = n.attribute("transform").map(parse_matrix).unwrap_or(Affine::IDENTITY);
            for c in n.children().filter(|c| c.is_element()) {
                aplanar(c, ts * t, capas, con_overlay, sin_grad, out);
            }
        }
        "path" => {
            let Some(d) = n.attribute("d") else { return };
            let Ok(bp) = BezPath::from_svg(d) else { return };
            let fill = n.attribute("fill").unwrap_or("none");
            let fo = attr_f(&n, "fill-opacity", 1.0);
            let relleno = if fill.starts_with("url(#") {
                if sin_grad { None } else { grad_de(&n, fill, fo) }
            } else if fill != "none" {
                hex(fill).map(|c| Relleno::Solido(c, fo))
            } else {
                None
            };
            let stroke = n.attribute("stroke").unwrap_or("none");
            let trazo = if stroke != "none" {
                hex(stroke).map(|c| Trazo {
                    col: c,
                    a: attr_f(&n, "stroke-opacity", 1.0),
                    w: attr_f(&n, "stroke-width", 1.0) as f64,
                    redondo_cap: n.attribute("stroke-linecap") == Some("round"),
                    redondo_join: n.attribute("stroke-linejoin") == Some("round"),
                })
            } else {
                None
            };
            if relleno.is_some() || trazo.is_some() {
                out.push(Item { path: bp, ts, evenodd: n.attribute("fill-rule") == Some("evenodd"), relleno, trazo });
            }
        }
        _ => {}
    }
}

fn stops_peniko(st: &[(f32, [u8; 3], f32)], op: f32) -> Vec<(f32, Color)> {
    let mut v: Vec<(f32, Color)> = st.iter().map(|&(o, c, a)| (o, Color::from_rgba8(c[0], c[1], c[2], a8(a * op)))).collect();
    // vello: paradas explicitas en 0 y 1 (Pad a mano), por si el relleno antes de la primera parada falla
    if let Some(&(o, c)) = v.first() {
        if o > 0.0 {
            v.insert(0, (0.0, c));
        }
    }
    if let Some(&(o, c)) = v.last() {
        if o < 1.0 {
            v.push((1.0, c));
        }
    }
    v
}

fn dibujar_items(scene: &mut Scene, items: &[Item], ts_pieza: Affine, op: f32) {
    for it in items {
        let m = ts_pieza * it.ts;
        let rule = if it.evenodd { Fill::EvenOdd } else { Fill::NonZero };
        match &it.relleno {
            Some(Relleno::Solido(c, fo)) => {
                scene.fill(rule, m, Color::from_rgba8(c[0], c[1], c[2], a8(fo * op)), None, &it.path);
            }
            Some(Relleno::Lineal { p1, p2, stops, tr, fo }) => {
                // puntos ya transformados por gradientTransform (brush_transform de vello dio otro resultado, ver <datos de trabajo omitidos>)
                let g = Gradient::new_linear(*tr * *p1, *tr * *p2).with_stops(stops_peniko(stops, fo * op).as_slice()).with_interpolation_alpha_space(vello::peniko::InterpolationAlphaSpace::Unpremultiplied);
                scene.fill(rule, m, &Brush::Gradient(g), None, &it.path);
            }
            Some(Relleno::Radial { c, r, stops, tr, fo }) => {
                let g = Gradient::new_radial(*c, *r).with_stops(stops_peniko(stops, fo * op).as_slice()).with_interpolation_alpha_space(vello::peniko::InterpolationAlphaSpace::Unpremultiplied);
                scene.fill(rule, m, &Brush::Gradient(g), Some(*tr), &it.path);
            }
            None => {}
        }
        if let Some(t) = &it.trazo {
            let st = Stroke::new(t.w)
                .with_caps(if t.redondo_cap { Cap::Round } else { Cap::Butt })
                .with_join(if t.redondo_join { Join::Round } else { Join::Miter });
            scene.stroke(&st, m, Color::from_rgba8(t.col[0], t.col[1], t.col[2], a8(t.a * op)), None, &it.path);
        }
    }
}

fn capas_de(v: &serde_json::Value) -> Option<Vec<String>> {
    v.as_array().map(|a| a.iter().filter_map(|c| c.as_str().map(|s| s.to_string())).collect())
}

struct Pieza {
    ts: Affine,
    op: f32,
    items: usize,
    cortes: Vec<Corte>,
}
struct Corte {
    inv: bool,
    mattes: Vec<(Affine, usize)>,
}
struct Escena {
    piezas: Vec<Pieza>,
}
struct Flags {
    con_overlay: bool,
    sin_recorte: bool,
    sin_grad: bool,
}
// Cache de dibujos aplanados, compartida entre cuadros (los SVG del plano se repiten entre cuadros: clave = ruta absoluta + capas).
#[derive(Default)]
struct Almacen {
    dibujos: Vec<Vec<Item>>,
    idx: HashMap<String, usize>,
    t_svg: f64,
    n_parse: usize,
    n_hit: usize,
}

fn dib(alm: &mut Almacen, base: &std::path::Path, rel: &str, capas: &Option<Vec<String>>, fl: &Flags) -> usize {
    let ruta = base.join(rel);
    let key = format!("{}|{:?}", ruta.display(), capas);
    if let Some(i) = alm.idx.get(&key) {
        alm.n_hit += 1;
        return *i;
    }
    let t = Instant::now();
    let txt = fs::read_to_string(&ruta).expect("svg");
    let doc = roxmltree::Document::parse(&txt).expect("xml");
    let mut v = Vec::new();
    aplanar(doc.root_element(), Affine::IDENTITY, capas, fl.con_overlay, fl.sin_grad, &mut v);
    alm.t_svg += ms(t);
    alm.n_parse += 1;
    alm.dibujos.push(v);
    alm.idx.insert(key, alm.dibujos.len() - 1);
    alm.dibujos.len() - 1
}

fn cargar(path: &str, a: &[String], w: u32, alm: &mut Almacen, fl: &Flags) -> Escena {
    let opt = |k: &str| a.iter().position(|x| x == k).and_then(|i| a.get(i + 1)).cloned();
    let j: serde_json::Value = serde_json::from_str(&fs::read_to_string(path).expect("leer escena.json")).expect("json");
    let base = std::path::Path::new(path).parent().unwrap().to_path_buf();
    let cam = &j["camara"];
    let g = |k: &str, d: f64| opt(&format!("--{}", k)).and_then(|s| s.parse().ok()).unwrap_or_else(|| cam[k].as_f64().unwrap_or(d));
    let (cx, cy, sx, sy, div) = (g("cx", 960.0), g("cy", 540.0), g("sx", 60.0), g("sy", 45.06), g("div", 1.0));
    let sw = w as f64 / 1920.0;
    let ts_de = |m: &serde_json::Value| -> Affine {
        let f = |r: usize, c: usize| m[r][c].as_f64().unwrap();
        let (a_, b_, tx, c_, d_, ty) = (f(0, 0) / div, f(0, 1) / div, f(0, 2), f(1, 0) / div, f(1, 1) / div, f(1, 2));
        let (kx, ky) = (sx * sw, -sy * sw);
        Affine::new([kx * a_, ky * c_, kx * b_, ky * d_, (cx + sx * tx) * sw, (cy - sy * ty) * sw]) * Affine::new([1.0, 0.0, 0.0, -1.0, 0.0, 0.0])
    };
    let mut piezas = Vec::new();
    for p in j["piezas"].as_array().unwrap() {
        let capas = capas_de(&p["capas"]);
        let items = dib(alm, &base, p["dibujo"].as_str().unwrap(), &capas, fl);
        let mut cortes = Vec::new();
        if !fl.sin_recorte {
            if let Some(v) = p["recorte"].as_array() {
                for c in v {
                    if !c["mattes"].as_array().map(|v| v.iter().all(|m| m.is_object())).unwrap_or(false) {
                        continue;
                    }
                    let mut mattes = Vec::new();
                    for m in c["mattes"].as_array().unwrap() {
                        let mi = dib(alm, &base, m["dibujo"].as_str().unwrap(), &capas_de(&m["capas"]), fl);
                        mattes.push((ts_de(&m["matriz_campo"]), mi));
                    }
                    cortes.push(Corte { inv: c["invertido"].as_bool().unwrap_or(false), mattes });
                }
            }
        }
        piezas.push(Pieza { ts: ts_de(&p["matriz_campo"]), op: p["opacidad"].as_f64().unwrap_or(1.0) as f32, items, cortes });
    }
    Escena { piezas }
}

fn construir(e: &Escena, alm: &Almacen, w: u32, h: u32, opacidad_grupo: bool) -> Scene {
    let mut scene = Scene::new();
    let rect = Rect::new(0.0, 0.0, w as f64, h as f64);
    for p in &e.piezas {
        if p.cortes.is_empty() {
            if opacidad_grupo && p.op < 1.0 {
                scene.push_layer(Fill::NonZero, Mix::Normal, p.op, Affine::IDENTITY, &rect);
                dibujar_items(&mut scene, &alm.dibujos[p.items], p.ts, 1.0);
                scene.pop_layer();
            } else {
                dibujar_items(&mut scene, &alm.dibujos[p.items], p.ts, p.op);
            }
        } else {
            // capas acotadas a la caja de la pieza (capas a pantalla completa desbordan los buffers de vello a >=4K con ~100 cutters)
            let pad = 16.0 * (w as f64 / 1920.0);
            let mut bb: Option<Rect> = None;
            for it in &alm.dibujos[p.items] {
                let r = (p.ts * it.ts).transform_rect_bbox(it.path.bounding_box());
                bb = Some(bb.map_or(r, |b| b.union(r)));
            }
            let Some(bb) = bb else { continue };
            let rect = Rect::new((bb.x0 - pad).max(0.0), (bb.y0 - pad).max(0.0), (bb.x1 + pad).min(w as f64), (bb.y1 + pad).min(h as f64));
            if rect.width() <= 0.0 || rect.height() <= 0.0 {
                continue;
            }
            scene.push_layer(Fill::NonZero, Mix::Normal, 1.0, Affine::IDENTITY, &rect);
            dibujar_items(&mut scene, &alm.dibujos[p.items], p.ts, p.op);
            for c in &p.cortes {
                let comp = if c.inv { Compose::DestIn } else { Compose::DestOut };
                scene.push_layer(Fill::NonZero, BlendMode::new(Mix::Normal, comp), 1.0, Affine::IDENTITY, &rect);
                for (m, di) in &c.mattes {
                    dibujar_items(&mut scene, &alm.dibujos[*di], *m, 1.0);
                }
                scene.pop_layer();
            }
            scene.pop_layer();
        }
    }
    scene
}

// copia de reducir_gauss del crate CPU, sobre RGBA8 en bruto (con fondo opaco premultiplicado == recto)
fn reducir_gauss(d: &[u8], w: usize, h: usize, ss: usize, sigma: f32, ow: usize, oh: usize) -> Vec<u8> {
    let s = (sigma * ss as f32).max(1e-3);
    let rad = (3.0 * s).ceil() as i64;
    let kern = |c: f32| -> Vec<(i64, f32)> {
        let c0 = c.round() as i64;
        let mut v: Vec<(i64, f32)> = (c0 - rad..=c0 + rad).map(|i| (i, (-((i as f32 - c).powi(2)) / (2.0 * s * s)).exp())).collect();
        let t: f32 = v.iter().map(|x| x.1).sum();
        v.iter_mut().for_each(|x| x.1 /= t);
        v
    };
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
    let mut od = vec![0u8; ow * oh * 4];
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
            let al = (acc[3] + 0.5).floor().clamp(0.0, 255.0);
            for ch in 0..3 {
                od[(oy * ow + x) * 4 + ch] = (acc[ch] + 0.5).floor().clamp(0.0, al) as u8;
            }
            od[(oy * ow + x) * 4 + 3] = al as u8;
        }
    }
    od
}

fn reducir_caja(d: &[u8], w: usize, ss: usize, ow: usize, oh: usize) -> Vec<u8> {
    let mut od = vec![0u8; ow * oh * 4];
    for oy in 0..oh {
        for ox in 0..ow {
            for ch in 0..4 {
                let mut s = 0u32;
                for dy in 0..ss {
                    for dx in 0..ss {
                        s += d[((oy * ss + dy) * w + ox * ss + dx) * 4 + ch] as u32;
                    }
                }
                od[(oy * ow + ox) * 4 + ch] = ((s + (ss * ss / 2) as u32) / (ss * ss) as u32) as u8;
            }
        }
    }
    od
}

fn guardar_png(path: &str, w: u32, h: u32, data: &[u8]) {
    let f = std::io::BufWriter::new(fs::File::create(path).expect("png"));
    let mut enc = png::Encoder::new(f, w, h);
    enc.set_color(png::ColorType::Rgba);
    enc.set_depth(png::BitDepth::Eight);
    enc.set_compression(png::Compression::Fast);
    enc.write_header().unwrap().write_image_data(data).unwrap();
}

fn ms(t: Instant) -> f64 {
    t.elapsed().as_secs_f64() * 1000.0
}


// ---- Gaussiano de Harmony en GPU (fase 2): misma matematica que reducir_gauss (separable, nucleo f32 normalizado, bordes clamp) ----
const WGSL: &str = r#"
struct P { w: u32, h: u32, ow: u32, oh: u32, ss: u32, rad: i32, off: i32, pad: u32 };
@group(0) @binding(0) var<uniform> p: P;
@group(0) @binding(1) var<storage, read> wt: array<f32>;
@group(0) @binding(2) var src: texture_storage_2d<rgba8unorm, read>;
@group(0) @binding(3) var<storage, read_write> tmp: array<vec4<f32>>;
@group(0) @binding(4) var<storage, read_write> dst: array<u32>;

@compute @workgroup_size(16, 16)
fn horiz(@builtin(global_invocation_id) g: vec3<u32>) {
    if (g.x >= p.ow || g.y >= p.h) { return; }
    let c0 = i32(g.x * p.ss) + p.off;
    var acc = vec4<f32>(0.0);
    let n = 2 * p.rad + 1;
    for (var k = 0; k < n; k = k + 1) {
        let x = clamp(c0 - p.rad + k, 0, i32(p.w) - 1);
        acc = acc + round(textureLoad(src, vec2<i32>(x, i32(g.y))) * 255.0) * wt[k];
    }
    tmp[g.y * p.ow + g.x] = acc;
}

@compute @workgroup_size(16, 16)
fn vert(@builtin(global_invocation_id) g: vec3<u32>) {
    if (g.x >= p.ow || g.y >= p.oh) { return; }
    let c0 = i32(g.y * p.ss) + p.off;
    var acc = vec4<f32>(0.0);
    let n = 2 * p.rad + 1;
    for (var k = 0; k < n; k = k + 1) {
        let y = clamp(c0 - p.rad + k, 0, i32(p.h) - 1);
        acc = acc + tmp[u32(y) * p.ow + g.x] * wt[k];
    }
    let al = clamp(floor(acc.w + 0.5), 0.0, 255.0);
    let r = u32(clamp(floor(acc.x + 0.5), 0.0, al));
    let gg = u32(clamp(floor(acc.y + 0.5), 0.0, al));
    let b = u32(clamp(floor(acc.z + 0.5), 0.0, al));
    dst[g.y * p.ow + g.x] = r | (gg << 8u) | (b << 16u) | (u32(al) << 24u);
}
"#;

struct GaussGpu {
    ph: wgpu::ComputePipeline,
    pv: wgpu::ComputePipeline,
    bg: wgpu::BindGroup,
    out: wgpu::Buffer,
    rd: wgpu::Buffer,
    ow: u32,
    oh: u32,
    h: u32,
}

fn crear_gauss(device: &wgpu::Device, queue: &wgpu::Queue, view: &wgpu::TextureView, w: u32, h: u32, ow: u32, oh: u32, ss: u32, sigma: f32) -> GaussGpu {
    let s = (sigma * ss as f32).max(1e-3);
    let rad = (3.0 * s).ceil() as i32;
    let c = (ss as f32 - 1.0) / 2.0;
    let off = c.round() as i32;
    let mut wts: Vec<f32> = (off - rad..=off + rad).map(|i| (-((i as f32 - c).powi(2)) / (2.0 * s * s)).exp()).collect();
    let t: f32 = wts.iter().sum();
    wts.iter_mut().for_each(|x| *x /= t);
    let bytes = |v: &[u32]| -> Vec<u8> { v.iter().flat_map(|x| x.to_le_bytes()).collect() };
    let uni = device.create_buffer(&wgpu::BufferDescriptor { label: Some("gauss_p"), size: 32, usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST, mapped_at_creation: false });
    queue.write_buffer(&uni, 0, &bytes(&[w, h, ow, oh, ss, rad as u32, off as u32, 0]));
    let wb = device.create_buffer(&wgpu::BufferDescriptor { label: Some("gauss_w"), size: (wts.len() * 4).max(16) as u64, usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST, mapped_at_creation: false });
    queue.write_buffer(&wb, 0, &wts.iter().flat_map(|x| x.to_le_bytes()).collect::<Vec<u8>>());
    let tmp = device.create_buffer(&wgpu::BufferDescriptor { label: Some("gauss_tmp"), size: ow as u64 * h as u64 * 16, usage: wgpu::BufferUsages::STORAGE, mapped_at_creation: false });
    let out = device.create_buffer(&wgpu::BufferDescriptor { label: Some("gauss_out"), size: ow as u64 * oh as u64 * 4, usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC, mapped_at_creation: false });
    let rd = device.create_buffer(&wgpu::BufferDescriptor { label: Some("gauss_rd"), size: ow as u64 * oh as u64 * 4, usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST, mapped_at_creation: false });
    let ent = |b: u32, ty: wgpu::BindingType| wgpu::BindGroupLayoutEntry { binding: b, visibility: wgpu::ShaderStages::COMPUTE, ty, count: None };
    let sb = |ro: bool| wgpu::BindingType::Buffer { ty: wgpu::BufferBindingType::Storage { read_only: ro }, has_dynamic_offset: false, min_binding_size: None };
    let bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: None,
        entries: &[
            ent(0, wgpu::BindingType::Buffer { ty: wgpu::BufferBindingType::Uniform, has_dynamic_offset: false, min_binding_size: None }),
            ent(1, sb(true)),
            ent(2, wgpu::BindingType::StorageTexture { access: wgpu::StorageTextureAccess::ReadOnly, format: wgpu::TextureFormat::Rgba8Unorm, view_dimension: wgpu::TextureViewDimension::D2 }),
            ent(3, sb(false)),
            ent(4, sb(false)),
        ],
    });
    let bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: None,
        layout: &bgl,
        entries: &[
            wgpu::BindGroupEntry { binding: 0, resource: uni.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 1, resource: wb.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 2, resource: wgpu::BindingResource::TextureView(view) },
            wgpu::BindGroupEntry { binding: 3, resource: tmp.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 4, resource: out.as_entire_binding() },
        ],
    });
    let pl = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor { label: None, bind_group_layouts: &[Some(&bgl)], immediate_size: 0 });
    let sm = device.create_shader_module(wgpu::ShaderModuleDescriptor { label: Some("gauss"), source: wgpu::ShaderSource::Wgsl(WGSL.into()) });
    let mk = |e: &str| device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor { label: Some(e), layout: Some(&pl), module: &sm, entry_point: Some(e), compilation_options: Default::default(), cache: None });
    GaussGpu { ph: mk("horiz"), pv: mk("vert"), bg, out, rd, ow, oh, h }
}

fn gauss_run(g: &GaussGpu, device: &wgpu::Device, queue: &wgpu::Queue) -> Vec<u8> {
    let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });
    {
        let mut cp = enc.begin_compute_pass(&wgpu::ComputePassDescriptor { label: None, timestamp_writes: None });
        cp.set_bind_group(0, &g.bg, &[]);
        cp.set_pipeline(&g.ph);
        cp.dispatch_workgroups(g.ow.div_ceil(16), g.h.div_ceil(16), 1);
    }
    {
        let mut cp = enc.begin_compute_pass(&wgpu::ComputePassDescriptor { label: None, timestamp_writes: None });
        cp.set_bind_group(0, &g.bg, &[]);
        cp.set_pipeline(&g.pv);
        cp.dispatch_workgroups(g.ow.div_ceil(16), g.oh.div_ceil(16), 1);
    }
    enc.copy_buffer_to_buffer(&g.out, 0, &g.rd, 0, g.ow as u64 * g.oh as u64 * 4);
    queue.submit(Some(enc.finish()));
    let slice = g.rd.slice(..);
    let (tx, rx) = std::sync::mpsc::channel();
    slice.map_async(wgpu::MapMode::Read, move |r| {
        tx.send(r).unwrap();
    });
    device.poll(wgpu::PollType::wait_indefinitely()).expect("poll");
    rx.recv().unwrap().expect("map");
    let v = slice.get_mapped_range().to_vec();
    g.rd.unmap();
    v
}

fn leer_textura(device: &wgpu::Device, queue: &wgpu::Queue, texture: &wgpu::Texture, buffer: &wgpu::Buffer, w: u32, h: u32) -> Vec<u8> {
    let unpadded = w * 4;
    let padded = unpadded.div_ceil(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT) * wgpu::COPY_BYTES_PER_ROW_ALIGNMENT;
    let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });
    enc.copy_texture_to_buffer(
        texture.as_image_copy(),
        wgpu::TexelCopyBufferInfo { buffer, layout: wgpu::TexelCopyBufferLayout { offset: 0, bytes_per_row: Some(padded), rows_per_image: None } },
        wgpu::Extent3d { width: w, height: h, depth_or_array_layers: 1 },
    );
    queue.submit(Some(enc.finish()));
    let slice = buffer.slice(..);
    let (tx, rx) = std::sync::mpsc::channel();
    slice.map_async(wgpu::MapMode::Read, move |r| {
        tx.send(r).unwrap();
    });
    device.poll(wgpu::PollType::wait_indefinitely()).expect("poll");
    rx.recv().unwrap().expect("map");
    let mut px = Vec::with_capacity((w * h * 4) as usize);
    {
        let data = slice.get_mapped_range();
        for row in 0..h {
            let s = (row * padded) as usize;
            px.extend_from_slice(&data[s..s + unpadded as usize]);
        }
    }
    buffer.unmap();
    px
}

fn entradas_de(a: &[String], opt: &dyn Fn(&str) -> Option<String>) -> (Vec<String>, bool) {
    if let Some(l) = opt("--lote") {
        let p = std::path::Path::new(&l);
        let v: Vec<String> = if p.is_dir() {
            let mut v: Vec<String> = fs::read_dir(p).unwrap().filter_map(|e| e.ok()).map(|e| e.path()).filter(|p| p.extension().map(|x| x == "json").unwrap_or(false)).map(|p| p.to_string_lossy().to_string()).collect();
            v.sort();
            v
        } else {
            fs::read_to_string(p).unwrap().lines().map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect()
        };
        (v, true)
    } else {
        (vec![a[1].clone()], false)
    }
}

fn main() {
    let a: Vec<String> = env::args().collect();
    if a.len() < 2 {
        eprintln!("uso: pegcraft-gpu <escena.json | --lote LISTA.txt|DIR --outdir D [--resumen R.json]> --out png [--size WxH] [--ss N] [--aa-gauss S] [--gauss-cpu] [--repetir N] [--sin-cache] [--hilos-png N] [--desglose] [--opacidad-grupo] [--sin-recorte] [--sin-gradientes] [--con-overlay] [--bg gris|transparente]");
        std::process::exit(2);
    }
    let opt = |k: &str| a.iter().position(|x| x == k).and_then(|i| a.get(i + 1)).cloned();
    let (entradas, lote) = entradas_de(&a, &opt);
    let out = opt("--out").unwrap_or("gpu.png".into());
    let outdir = opt("--outdir").unwrap_or(".".into());
    let (ow, oh) = opt("--size").and_then(|s| s.split_once('x').map(|(w, h)| (w.parse::<u32>().unwrap(), h.parse::<u32>().unwrap()))).unwrap_or((1920, 1080));
    let aa_gauss: Option<f32> = opt("--aa-gauss").and_then(|s| s.parse().ok());
    let gauss_cpu = a.iter().any(|x| x == "--gauss-cpu");
    let ss: u32 = opt("--ss").and_then(|s| s.parse().ok()).unwrap_or(1).max(1);
    let repetir: usize = opt("--repetir").and_then(|s| s.parse().ok()).unwrap_or(1).max(1);
    let hilos_png: usize = opt("--hilos-png").and_then(|s| s.parse().ok()).unwrap_or(3).max(1);
    let sin_cache = a.iter().any(|x| x == "--sin-cache");
    let desglose = a.iter().any(|x| x == "--desglose");
    let opacidad_grupo = a.iter().any(|x| x == "--opacidad-grupo");
    let gris = opt("--bg").as_deref() != Some("transparente");
    let (w, h) = (ow * ss, oh * ss);
    let fl = Flags { con_overlay: a.iter().any(|x| x == "--con-overlay"), sin_recorte: a.iter().any(|x| x == "--sin-recorte"), sin_grad: a.iter().any(|x| x == "--sin-gradientes") };
    if lote {
        fs::create_dir_all(&outdir).ok();
    }

    let t0 = Instant::now();
    let instance = wgpu::Instance::default();
    let adapter = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions { power_preference: wgpu::PowerPreference::HighPerformance, force_fallback_adapter: false, compatible_surface: None })).expect("adaptador");
    let nombre = adapter.get_info().name.clone();
    let (device, queue) = pollster::block_on(adapter.request_device(&wgpu::DeviceDescriptor { required_limits: adapter.limits(), ..Default::default() })).expect("device");
    device.on_uncaptured_error(std::sync::Arc::new(|e| eprintln!("wgpu error: {e}")));
    let mut renderer = vello::Renderer::new(&device, vello::RendererOptions { use_cpu: false, antialiasing_support: vello::AaSupport::area_only(), num_init_threads: std::num::NonZeroUsize::new(1), pipeline_cache: None }).expect("renderer");
    let texture = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("pegcraft-gpu"),
        size: wgpu::Extent3d { width: w, height: h, depth_or_array_layers: 1 },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: wgpu::TextureFormat::Rgba8Unorm,
        usage: wgpu::TextureUsages::STORAGE_BINDING | wgpu::TextureUsages::COPY_SRC,
        view_formats: &[],
    });
    let view = texture.create_view(&wgpu::TextureViewDescriptor::default());
    let padded = (w * 4).div_ceil(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT) * wgpu::COPY_BYTES_PER_ROW_ALIGNMENT;
    let buffer = device.create_buffer(&wgpu::BufferDescriptor { label: Some("lectura"), size: (padded * h) as u64, usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ, mapped_at_creation: false });
    // GPU: gaussiano en compute salvo --gauss-cpu; sin --aa-gauss y ss>1 -> caja en CPU (no es el camino de calidad)
    let gauss = match aa_gauss {
        Some(sg) if !gauss_cpu => Some(crear_gauss(&device, &queue, &view, w, h, ow, oh, ss, sg)),
        _ => None,
    };
    let t_init = ms(t0);
    let base_color = if gris { Color::from_rgba8(128, 128, 128, 255) } else { Color::from_rgba8(0, 0, 0, 0) };

    // escritores de PNG en hilos (solapan la codificacion con el siguiente cuadro)
    let (txp, rxp) = std::sync::mpsc::channel::<(String, Vec<u8>)>();
    let rxp = std::sync::Arc::new(std::sync::Mutex::new(rxp));
    let hs: Vec<_> = (0..hilos_png)
        .map(|_| {
            let rx = rxp.clone();
            std::thread::spawn(move || loop {
                let m = rx.lock().unwrap().recv();
                match m {
                    Ok((p, d)) => guardar_png(&p, ow, oh, &d),
                    Err(_) => break,
                }
            })
        })
        .collect();

    let mut alm = Almacen::default();
    let mut filas: Vec<serde_json::Value> = Vec::new();
    let mut tot: Vec<[f64; 8]> = Vec::new(); // json+carga, svg, escena, render_submit, gpu_vello, gauss+lectura, reducir cpu, total
    let tw = Instant::now();
    for rep in 0..repetir {
        for (k, e) in entradas.iter().enumerate() {
            let ti = Instant::now();
            if sin_cache {
                alm = Almacen::default();
            }
            let svg0 = alm.t_svg;
            let (p0, h0) = (alm.n_parse, alm.n_hit);
            let t = Instant::now();
            let esc = cargar(e, &a, w, &mut alm, &fl);
            let t_svg = alm.t_svg - svg0;
            let t_json = ms(t) - t_svg;
            let t = Instant::now();
            let scene = construir(&esc, &alm, w, h, opacidad_grupo);
            let t_scene = ms(t);
            let t = Instant::now();
            let params = vello::RenderParams { base_color, width: w, height: h, antialiasing_method: vello::AaConfig::Area };
            renderer.render_to_texture(&device, &queue, &scene, &view, &params).expect("render");
            let t_render = ms(t);
            let mut t_vgpu = 0.0;
            if desglose {
                let t = Instant::now();
                device.poll(wgpu::PollType::wait_indefinitely()).expect("poll");
                t_vgpu = ms(t);
            }
            let t = Instant::now();
            let (fin, t_red) = if let Some(g) = &gauss {
                (gauss_run(g, &device, &queue), 0.0)
            } else {
                let px = leer_textura(&device, &queue, &texture, &buffer, w, h);
                let t2 = Instant::now();
                let f = match aa_gauss {
                    Some(sg) => reducir_gauss(&px, w as usize, h as usize, ss as usize, sg, ow as usize, oh as usize),
                    None if ss > 1 => reducir_caja(&px, w as usize, ss as usize, ow as usize, oh as usize),
                    None => px,
                };
                (f, ms(t2))
            };
            let t_lect = ms(t) - t_red;
            let total = ms(ti);
            tot.push([t_json, t_svg, t_scene, t_render, t_vgpu, t_lect, t_red, total]);
            if rep == repetir - 1 {
                let dest = if lote { format!("{}/{}.png", outdir, std::path::Path::new(e).file_stem().unwrap().to_string_lossy()) } else { out.clone() };
                if lote || k == entradas.len() - 1 {
                    txp.send((dest, fin)).unwrap();
                }
                filas.push(serde_json::json!({"escena": e, "json_ms": t_json, "svg_ms": t_svg, "svg_parseados": alm.n_parse - p0, "svg_cache": alm.n_hit - h0, "scene_ms": t_scene, "render_submit_ms": t_render, "gpu_vello_ms": t_vgpu, "gauss_lectura_ms": t_lect, "reducir_cpu_ms": t_red, "cuadro_ms": total}));
            }
        }
    }
    let t_loop = ms(tw);
    drop(txp);
    let tpng = Instant::now();
    for hh in hs {
        hh.join().ok();
    }
    let t_png_cola = ms(tpng);
    let t_wall = ms(tw);
    let n = tot.len();
    let skip = if n > 1 && !lote { 1 } else { 0 };
    let m = |i: usize| tot.iter().skip(skip).map(|f| f[i]).sum::<f64>() / (n - skip) as f64;
    let n_items: usize = alm.dibujos.iter().map(|d| d.len()).sum();
    let r = serde_json::json!({
        "adaptador": nombre, "size": format!("{}x{}", ow, oh), "ss": ss, "gauss": if aa_gauss.is_none() { "no" } else if gauss.is_some() { "gpu" } else { "cpu" },
        "cuadros": n, "dibujos_cache": alm.dibujos.len(), "items_cache": n_items, "init_gpu_ms": t_init, "primer_cuadro_ms": tot[0][7],
        "medio_ms": {"json_carga": m(0), "svg": m(1), "scene": m(2), "render_submit": m(3), "gpu_vello": m(4), "gauss_lectura": m(5), "reducir_cpu": m(6), "cuadro": m(7)},
        "lote_sin_png_ms": t_loop, "espera_png_ms": t_png_cola, "pared_ms": t_wall, "cuadros_por_s": n as f64 * 1000.0 / t_wall,
        "frames": if lote { serde_json::Value::Array(filas) } else { serde_json::Value::Null },
    });
    if let Some(rp) = opt("--resumen") {
        fs::write(rp, serde_json::to_string_pretty(&r).unwrap()).ok();
    }
    let mut c = r.clone();
    if lote {
        c["frames"] = serde_json::Value::Null;
    }
    println!("{}", serde_json::to_string(&c).unwrap());
}
