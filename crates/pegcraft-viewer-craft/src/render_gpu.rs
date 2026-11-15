// Rasterizado por GPU (vello sobre wgpu) para el visor: la casilla «Acelerar por GPU».
// ATRIBUCION: el parseo SVG -> items (matriz, capas, degradados) y la construccion de la escena de vello (opacidad de grupo, cutters como capas
// DestOut/DestIn) vienen del spike ../pegcraft-gpu/src/main.rs (mismo repo), adaptados a `render::Escena`/`Estado`/`Edit` del visor: la matriz de
// cada pieza sale de `render::ts_de` (la misma del CPU, con las ediciones) y las piezas ocultas se saltan igual.
// Vello usa su PROPIO device wgpu 29 (eframe usa wgpu 30: no se comparten texturas), asi que el cuadro se lee de vuelta a la CPU y se sube como imagen.
//
// Lo que iguala del CPU (render.rs): fondo gris 128, capas underlay/colour/line/overlay (overlay solo si la pieza lo pide), opacidad de GRUPO por pieza
// (CPU: dibuja la pieza a un lienzo y lo compone con la opacidad), recortes (mattes de un cutter se unen; no invertido = 1-alfa del matte, invertido = alfa),
// ocultas y ediciones. Diferencias conocidas (ver la interfaz): el antialias de vello no es el de tiny-skia (bordes ligeramente distintos), y la GPU SI dibuja
// degradados (el CPU del visor los ignora). Ninguno de los dos hace la mezcla aditiva «glow suma» ni difumina mattes (solo existe en el CLI pegcraft-render).
use crate::render::{ts_de, Cache, Calidad, Escena, Estado, M};
use std::{
    collections::HashMap,
    path::PathBuf,
    rc::Rc,
    sync::{atomic::AtomicBool, atomic::Ordering, Arc, Mutex},
};
use tiny_skia::Pixmap;
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
pub struct Item {
    path: BezPath,
    ts: Affine,
    evenodd: bool,
    relleno: Option<Relleno>,
    trazo: Option<Trazo>,
    capa: Option<&'static str>,
    caja: Rect, // caja del path en sus coordenadas
}
pub struct DibujoGpu {
    items: Vec<Item>,
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

// Aplana un SVG a items, marcando la capa de cada uno (el filtro por capas de la pieza se aplica al dibujar: un SVG se parsea una vez).
fn aplanar(n: roxmltree::Node, ts: Affine, capa: Option<&'static str>, out: &mut Vec<Item>) {
    match n.tag_name().name() {
        "g" | "svg" => {
            let mut capa = capa;
            if let Some(id) = n.attribute("id") {
                if let Some(c) = CAPAS.iter().find(|c| **c == id) {
                    capa = Some(c);
                }
            }
            let t = n.attribute("transform").map(parse_matrix).unwrap_or(Affine::IDENTITY);
            for c in n.children().filter(|c| c.is_element()) {
                aplanar(c, ts * t, capa, out);
            }
        }
        "path" => {
            let Some(d) = n.attribute("d") else { return };
            let Ok(bp) = BezPath::from_svg(d) else { return };
            let fill = n.attribute("fill").unwrap_or("none");
            let fo = attr_f(&n, "fill-opacity", 1.0);
            let relleno = if fill.starts_with("url(#") {
                grad_de(&n, fill, fo)
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
                let caja = bp.bounding_box();
                out.push(Item { path: bp, ts, evenodd: n.attribute("fill-rule") == Some("evenodd"), relleno, trazo, capa, caja });
            }
        }
        _ => {}
    }
}

fn permitida(capa: Option<&'static str>, capas: &Option<Vec<String>>) -> bool {
    match (capa, capas) {
        (None, _) => true,
        (Some(c), Some(l)) => l.iter().any(|x| x == c),
        (Some(c), None) => c != "overlay",
    }
}

fn stops_peniko(st: &[(f32, [u8; 3], f32)]) -> Vec<(f32, Color)> {
    let mut v: Vec<(f32, Color)> = st.iter().map(|&(o, c, a)| (o, Color::from_rgba8(c[0], c[1], c[2], a8(a)))).collect();
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

/// la opacidad de la pieza va como alfa de la capa de grupo (como el CPU), no por path
fn dibujar_items(scene: &mut Scene, d: &DibujoGpu, ts_pieza: Affine, capas: &Option<Vec<String>>) {
    for it in d.items.iter().filter(|i| permitida(i.capa, capas)) {
        let m = ts_pieza * it.ts;
        let rule = if it.evenodd { Fill::EvenOdd } else { Fill::NonZero };
        match &it.relleno {
            Some(Relleno::Solido(c, fo)) => {
                scene.fill(rule, m, Color::from_rgba8(c[0], c[1], c[2], a8(*fo)), None, &it.path);
            }
            Some(Relleno::Lineal { p1, p2, stops, tr, fo }) => {
                let st: Vec<(f32, [u8; 3], f32)> = stops.iter().map(|&(o, c, a)| (o, c, a * fo)).collect();
                let g = Gradient::new_linear(*tr * *p1, *tr * *p2).with_stops(stops_peniko(&st).as_slice()).with_interpolation_alpha_space(vello::peniko::InterpolationAlphaSpace::Unpremultiplied);
                scene.fill(rule, m, &Brush::Gradient(g), None, &it.path);
            }
            Some(Relleno::Radial { c, r, stops, tr, fo }) => {
                let st: Vec<(f32, [u8; 3], f32)> = stops.iter().map(|&(o, c, a)| (o, c, a * fo)).collect();
                let g = Gradient::new_radial(*c, *r).with_stops(stops_peniko(&st).as_slice()).with_interpolation_alpha_space(vello::peniko::InterpolationAlphaSpace::Unpremultiplied);
                scene.fill(rule, m, &Brush::Gradient(g), Some(*tr), &it.path);
            }
            None => {}
        }
        if let Some(t) = &it.trazo {
            let st = Stroke::new(t.w)
                .with_caps(if t.redondo_cap { Cap::Round } else { Cap::Butt })
                .with_join(if t.redondo_join { Join::Round } else { Join::Miter });
            scene.stroke(&st, m, Color::from_rgba8(t.col[0], t.col[1], t.col[2], a8(t.a)), None, &it.path);
        }
    }
}

fn a_affine(t: tiny_skia::Transform) -> Affine {
    Affine::new([t.sx as f64, t.ky as f64, t.kx as f64, t.sy as f64, t.tx as f64, t.ty as f64])
}

/// caja en pixeles de los items permitidos de un dibujo bajo `m`, con margen por el ancho de trazo (union)
fn caja_px(d: &DibujoGpu, m: Affine, capas: &Option<Vec<String>>, acc: &mut Option<Rect>) {
    for it in d.items.iter().filter(|i| permitida(i.capa, capas)) {
        let mi = m * it.ts;
        let ci = mi.as_coeffs();
        let ki = ci[0].abs().max(ci[1].abs()).max(ci[2].abs()).max(ci[3].abs());
        let infl = it.trazo.as_ref().map(|t| 2.0 * t.w * ki + 2.0).unwrap_or(1.0);
        let r = mi.transform_rect_bbox(it.caja).inflate(infl, infl);
        *acc = Some(acc.map_or(r, |b| b.union(r)));
    }
}

struct Destino {
    w: u32,
    h: u32,
    tex: wgpu::Texture,
    view: wgpu::TextureView,
    buf: wgpu::Buffer,
}

/// Dispositivo vello + cache de dibujos aplanados + textura de salida. Un solo hilo (el de la interfaz).
pub struct Gpu {
    device: wgpu::Device,
    queue: wgpu::Queue,
    renderer: vello::Renderer,
    pub adaptador: String,
    pub init_ms: f32,
    dest: Option<Destino>,
    dibujos: HashMap<PathBuf, Option<Rc<DibujoGpu>>>,
    error: Arc<Mutex<Option<String>>>,
    perdido: Arc<AtomicBool>,
}

impl Gpu {
    pub fn nuevo() -> Result<Gpu, String> {
        let t0 = std::time::Instant::now();
        let r = std::panic::catch_unwind(|| -> Result<Gpu, String> {
            let instance = wgpu::Instance::default();
            let adapter = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
                power_preference: wgpu::PowerPreference::HighPerformance,
                force_fallback_adapter: false,
                compatible_surface: None,
            }))
            .map_err(|e| format!("sin adaptador GPU: {e}"))?;
            let nombre = adapter.get_info().name.clone();
            let (device, queue) = pollster::block_on(adapter.request_device(&wgpu::DeviceDescriptor { required_limits: adapter.limits(), ..Default::default() }))
                .map_err(|e| format!("no se pudo abrir la GPU ({nombre}): {e}"))?;
            let error: Arc<Mutex<Option<String>>> = Arc::new(Mutex::new(None));
            let e2 = error.clone();
            device.on_uncaptured_error(Arc::new(move |e| {
                eprintln!("wgpu (vello): {e}");
                *e2.lock().unwrap() = Some(e.to_string());
            }));
            let perdido = Arc::new(AtomicBool::new(false));
            let p2 = perdido.clone();
            device.set_device_lost_callback(move |_, msg| {
                eprintln!("wgpu (vello): dispositivo perdido: {msg}");
                p2.store(true, Ordering::SeqCst);
            });
            let renderer = vello::Renderer::new(
                &device,
                vello::RendererOptions { use_cpu: false, antialiasing_support: vello::AaSupport::area_only(), num_init_threads: std::num::NonZeroUsize::new(1), pipeline_cache: None },
            )
            .map_err(|e| format!("vello: {e}"))?;
            Ok(Gpu { device, queue, renderer, adaptador: nombre, init_ms: 0.0, dest: None, dibujos: HashMap::new(), error, perdido })
        });
        match r {
            Ok(Ok(mut g)) => {
                g.init_ms = t0.elapsed().as_secs_f32() * 1000.0;
                Ok(g)
            }
            Ok(Err(e)) => Err(e),
            Err(_) => Err("la GPU se cayó al iniciarse".into()),
        }
    }

    pub fn vaciar_cache(&mut self) {
        self.dibujos.clear();
    }
    pub fn n_dibujos(&self) -> usize {
        self.dibujos.len()
    }

    fn dibujo(&mut self, p: PathBuf) -> Option<Rc<DibujoGpu>> {
        let p = Cache::limpiar(&p);
        self.dibujos
            .entry(p.clone())
            .or_insert_with(|| {
                let txt = std::fs::read_to_string(&p).ok()?;
                let doc = roxmltree::Document::parse(&txt).ok()?;
                let mut items = vec![];
                aplanar(doc.root_element(), Affine::IDENTITY, None, &mut items);
                Some(Rc::new(DibujoGpu { items }))
            })
            .clone()
    }

    fn escena(&mut self, e: &Escena, st: &Estado, w: u32, h: u32) -> Scene {
        let mut scene = Scene::new();
        let (fw, fh) = (w as f64, h as f64);
        for p in &e.piezas {
            if st.ocultas.contains(&p.key) {
                continue;
            }
            let ed = st.ediciones.get(&p.key);
            let op = (p.opacidad * ed.map(|x| x.op).unwrap_or(1.0)).clamp(0.0, 1.0);
            let Some(d) = self.dibujo(e.base.join(&p.dibujo)) else { continue };
            let m = a_affine(ts_de(e, &p.m, ed, w));
            let mut bb: Option<Rect> = None;
            caja_px(&d, m, &p.capas, &mut bb);
            let Some(bb) = bb else { continue };
            // capas acotadas a la caja de la pieza (a pantalla completa desbordan los buffers de vello con ~100 cutters)
            let rect = Rect::new(bb.x0.max(0.0), bb.y0.max(0.0), bb.x1.min(fw), bb.y1.min(fh));
            if rect.width() <= 0.0 || rect.height() <= 0.0 {
                continue;
            }
            if p.recorte.is_empty() {
                if op >= 0.999 {
                    dibujar_items(&mut scene, &d, m, &p.capas);
                } else {
                    scene.push_layer(Fill::NonZero, Mix::Normal, op, Affine::IDENTITY, &rect);
                    dibujar_items(&mut scene, &d, m, &p.capas);
                    scene.pop_layer();
                }
            } else {
                scene.push_layer(Fill::NonZero, Mix::Normal, op, Affine::IDENTITY, &rect);
                dibujar_items(&mut scene, &d, m, &p.capas);
                for c in &p.recorte {
                    let comp = if c.inv { Compose::DestIn } else { Compose::DestOut };
                    scene.push_layer(Fill::NonZero, BlendMode::new(Mix::Normal, comp), 1.0, Affine::IDENTITY, &rect);
                    for mt in &c.mattes {
                        if let Some(md) = self.dibujo(e.base.join(&mt.dibujo)) {
                            let mm: &M = &mt.m;
                            dibujar_items(&mut scene, &md, a_affine(ts_de(e, mm, None, w)), &mt.capas);
                        }
                    }
                    scene.pop_layer();
                }
                scene.pop_layer();
            }
        }
        scene
    }

    fn destino(&mut self, w: u32, h: u32) {
        if self.dest.as_ref().map(|d| (d.w, d.h)) == Some((w, h)) {
            return;
        }
        let tex = self.device.create_texture(&wgpu::TextureDescriptor {
            label: Some("pegcraft-gpu"),
            size: wgpu::Extent3d { width: w, height: h, depth_or_array_layers: 1 },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8Unorm,
            usage: wgpu::TextureUsages::STORAGE_BINDING | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let view = tex.create_view(&wgpu::TextureViewDescriptor::default());
        let padded = (w * 4).div_ceil(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT) * wgpu::COPY_BYTES_PER_ROW_ALIGNMENT;
        let buf = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("lectura"),
            size: (padded * h) as u64,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        self.dest = Some(Destino { w, h, tex, view, buf });
    }

    fn leer(&mut self) -> Result<Vec<u8>, String> {
        let d = self.dest.as_ref().unwrap();
        let (w, h) = (d.w, d.h);
        let unpadded = w * 4;
        let padded = unpadded.div_ceil(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT) * wgpu::COPY_BYTES_PER_ROW_ALIGNMENT;
        let mut enc = self.device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });
        enc.copy_texture_to_buffer(
            d.tex.as_image_copy(),
            wgpu::TexelCopyBufferInfo { buffer: &d.buf, layout: wgpu::TexelCopyBufferLayout { offset: 0, bytes_per_row: Some(padded), rows_per_image: None } },
            wgpu::Extent3d { width: w, height: h, depth_or_array_layers: 1 },
        );
        self.queue.submit(Some(enc.finish()));
        let slice = d.buf.slice(..);
        let (tx, rx) = std::sync::mpsc::channel();
        slice.map_async(wgpu::MapMode::Read, move |r| {
            let _ = tx.send(r);
        });
        self.device.poll(wgpu::PollType::wait_indefinitely()).map_err(|e| format!("poll: {e}"))?;
        rx.recv().map_err(|e| e.to_string())?.map_err(|e| format!("map: {e}"))?;
        let mut px = Vec::with_capacity((w * h * 4) as usize);
        {
            let data = slice.get_mapped_range();
            for row in 0..h {
                let s = (row * padded) as usize;
                px.extend_from_slice(&data[s..s + unpadded as usize]);
            }
        }
        d.buf.unmap();
        Ok(px)
    }

    /// Dibuja un fotograma. Calidad::Exacta no se hace aqui (el llamador la deja en CPU). `gris=false` -> fondo transparente (comparaciones de alfa).
    pub fn render(&mut self, e: &Escena, st: &Estado, q: Calidad, gris: bool) -> Result<Pixmap, String> {
        if self.perdido.load(Ordering::SeqCst) {
            return Err("la GPU dejó de responder (dispositivo perdido)".into());
        }
        *self.error.lock().unwrap() = None;
        let (w, h) = q.out(e.tam);
        let r = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| -> Result<Vec<u8>, String> {
            let scene = self.escena(e, st, w, h);
            self.destino(w, h);
            let base_color = if gris { Color::from_rgba8(128, 128, 128, 255) } else { Color::from_rgba8(0, 0, 0, 0) };
            let params = vello::RenderParams { base_color, width: w, height: h, antialiasing_method: vello::AaConfig::Area };
            let view = &self.dest.as_ref().unwrap().view;
            self.renderer.render_to_texture(&self.device, &self.queue, &scene, view, &params).map_err(|e| format!("vello: {e}"))?;
            self.leer()
        }));
        let px = match r {
            Ok(Ok(px)) => px,
            Ok(Err(e)) => return Err(e),
            Err(_) => return Err("la GPU falló al dibujar (panic en vello/wgpu)".into()),
        };
        if let Some(e) = self.error.lock().unwrap().take() {
            return Err(format!("error de wgpu: {e}"));
        }
        let size = tiny_skia::IntSize::from_wh(w, h).ok_or("tamaño inválido")?;
        Pixmap::from_vec(px, size).ok_or_else(|| "pixmap".to_string())
    }
}
