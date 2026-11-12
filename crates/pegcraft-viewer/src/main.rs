// pegcraft-viewer: SPIKE de visor para escenas Harmony horneadas (player + capas + parametros + nodos). Ver (doc interna omitida)
// Bucle propio winit 0.30 + egui 0.35 + egui-wgpu (wgpu 29), sin eframe: mismo esquema que otro proyecto-app\src\main.rs (referencia, no obligacion).
// SOLO LECTURA sobre el horneado: las ediciones viven en memoria y nunca se escriben al .xstage ni a los .tvg.
mod nodos;
mod render;

use egui_wgpu::wgpu;
use render::{Cache, Calidad, Edit, Escena, Estado};
use std::{collections::HashMap, path::PathBuf, sync::Arc, time::Instant};
use winit::{
    application::ApplicationHandler,
    dpi::PhysicalSize,
    event::WindowEvent,
    event_loop::{ActiveEventLoop, ControlFlow, EventLoop},
    window::{Window, WindowId},
};

struct Opciones {
    ruta: PathBuf,
    grafo: Option<PathBuf>,
    shot: Option<PathBuf>,
    frame: usize,
    ocultar: Vec<String>,
    editar: Vec<String>,
    seleccionar: Option<String>,
    nodos: bool,
    calidad: Calidad,
    medir: bool,
    tam: (u32, u32),
    tab_nodos_grande: bool,
}

fn args() -> Opciones {
    let a: Vec<String> = std::env::args().skip(1).collect();
    let mut o = Opciones {
        ruta: PathBuf::from(r"trabajo\horneado"),
        grafo: None,
        shot: None,
        frame: 0,
        ocultar: vec![],
        editar: vec![],
        seleccionar: None,
        nodos: false,
        calidad: Calidad::Rapida,
        medir: false,
        tam: (1600, 900),
        tab_nodos_grande: false,
    };
    let mut i = 0;
    while i < a.len() {
        let sig = |i: usize| a.get(i + 1).cloned().unwrap_or_default();
        match a[i].as_str() {
            "--grafo" => { o.grafo = Some(sig(i).into()); i += 1 }
            "--screenshot" => { o.shot = Some(sig(i).into()); i += 1 }
            "--frame" => { o.frame = sig(i).parse().unwrap_or(0); i += 1 }
            "--ocultar" => { o.ocultar.push(sig(i)); i += 1 }
            "--editar" => { o.editar.push(sig(i)); i += 1 }
            "--seleccionar" => { o.seleccionar = Some(sig(i)); i += 1 }
            "--nodos" => o.nodos = true,
            "--nodos-grande" => { o.nodos = true; o.tab_nodos_grande = true }
            "--medir" => o.medir = true,
            "--calidad" => { o.calidad = match sig(i).as_str() { "completa" => Calidad::Completa, "exacta" => Calidad::Exacta, _ => Calidad::Rapida }; i += 1 }
            "--tam" => { if let Some((w, h)) = sig(i).split_once('x') { o.tam = (w.parse().unwrap_or(1600), h.parse().unwrap_or(900)); } i += 1 }
            s if !s.starts_with("--") => o.ruta = s.into(),
            _ => {}
        }
        i += 1;
    }
    if o.grafo.is_none() {
        let d = PathBuf::from(r"trabajo\visor\grafo.json");
        if d.exists() { o.grafo = Some(d); }
    }
    o
}

fn descubrir(ruta: &std::path::Path) -> Vec<PathBuf> {
    if ruta.is_file() { return vec![ruta.to_path_buf()]; }
    let mut v: Vec<PathBuf> = std::fs::read_dir(ruta).map(|d| d.filter_map(|e| e.ok()).map(|e| e.path()).filter(|p| {
        let n = p.file_name().and_then(|n| n.to_str()).unwrap_or("");
        n.starts_with("escena_f") && n.ends_with(".json")
    }).collect()).unwrap_or_default();
    v.sort();
    if v.is_empty() && ruta.join("escena.json").exists() { v.push(ruta.join("escena.json")); }
    v
}

struct Visor {
    frames: Vec<Escena>,
    cur: usize,
    playing: bool,
    t_play: Instant,
    fps: f32,
    cache: Cache,
    estado: Estado,
    version: u64,
    sel: Option<String>, // key de la pieza
    filtro: String,
    q: Calidad,
    texs: HashMap<usize, egui::TextureHandle>,
    ultimo_ms: f32,
    log_ms: Vec<(String, f32)>,
    grafo: Option<nodos::Grafo>,
    vista: nodos::Vista,
    nodos_abierto: bool,
    nodos_grande: bool,
    msg: String,
}

impl Visor {
    fn nuevo(o: &Opciones) -> Result<Self, String> {
        let rutas = descubrir(&o.ruta);
        if rutas.is_empty() { return Err(format!("no hay escenas en {:?}", o.ruta)); }
        let frames: Vec<Escena> = rutas.iter().map(|r| render::cargar(r)).collect::<Result<_, _>>()?;
        let grafo = o.grafo.as_ref().and_then(|g| nodos::cargar(g).map_err(|e| eprintln!("grafo: {e}")).ok());
        let raiz = grafo.as_ref().map(|g| g.raiz.clone()).unwrap_or("Top".into());
        let mut v = Visor {
            cur: o.frame.min(frames.len() - 1), frames, playing: false, t_play: Instant::now(), fps: 24.0, cache: Cache::default(), estado: Estado::default(),
            version: 0, sel: None, filtro: String::new(), q: o.calidad, texs: HashMap::new(), ultimo_ms: 0.0, log_ms: vec![], grafo,
            vista: nodos::Vista::nueva(&raiz), nodos_abierto: o.nodos, nodos_grande: o.tab_nodos_grande, msg: String::new(),
        };
        for s in &o.ocultar {
            if let Some(p) = v.frames[v.cur].piezas.iter().find(|p| p.key.contains(s.as_str())) { v.estado.ocultas.insert(p.key.clone()); }
        }
        for e in &o.editar {
            if let Some((sub, kv)) = e.split_once(':') {
                if let Some(p) = v.frames[v.cur].piezas.iter().find(|p| p.key.contains(sub)) {
                    let mut ed = Edit::default();
                    for par in kv.split(',') {
                        if let Some((k, val)) = par.split_once('=') {
                            let x: f32 = val.parse().unwrap_or(0.0);
                            match k { "dx" => ed.dx = x, "dy" => ed.dy = x, "rot" => ed.rot = x, "esc" => { ed.esc = x; ed.escy = x }, "op" => ed.op = x, _ => {} }
                        }
                    }
                    v.estado.ediciones.insert(p.key.clone(), ed);
                }
            }
        }
        if let Some(s) = &o.seleccionar {
            v.sel = v.frames[v.cur].piezas.iter().find(|p| p.key.contains(s.as_str())).map(|p| p.key.clone());
            v.sincronizar_nodos();
        }
        Ok(v)
    }

    fn sincronizar_nodos(&mut self) {
        if let (Some(g), Some(k)) = (&self.grafo, &self.sel) {
            if let Some(p) = self.frames[self.cur].piezas.iter().find(|p| &p.key == k) {
                let id = p.id.clone();
                self.vista.ir_a(g, &id);
            }
        }
    }
    fn invalidar(&mut self) {
        self.version += 1;
        self.texs.clear();
    }
    fn textura(&mut self, ctx: &egui::Context) -> Option<egui::TextureHandle> {
        if !self.texs.contains_key(&self.cur) {
            let t0 = Instant::now();
            let pm = render::render(&self.frames[self.cur], &mut self.cache, &self.estado, self.q);
            self.ultimo_ms = t0.elapsed().as_secs_f32() * 1000.0;
            let img = egui::ColorImage::from_rgba_premultiplied([pm.width() as usize, pm.height() as usize], pm.data());
            self.texs.insert(self.cur, ctx.load_texture(format!("cuadro{}", self.cur), img, egui::TextureOptions::LINEAR));
        }
        self.texs.get(&self.cur).cloned()
    }

    fn ui(&mut self, ui: &mut egui::Ui) {
        let ctx = ui.ctx().clone();
        if self.playing && self.t_play.elapsed().as_secs_f32() >= 1.0 / self.fps {
            self.t_play = Instant::now();
            self.cur = (self.cur + 1) % self.frames.len();
        }
        if self.playing { ctx.request_repaint(); }
        egui::Panel::top("barra").show(ui, |ui| {
            ui.horizontal(|ui| {
                ui.strong("pegcraft-viewer (spike)");
                ui.separator();
                ui.checkbox(&mut self.nodos_abierto, "Nodos");
                let q0 = self.q;
                egui::ComboBox::from_id_salt("calidad").selected_text(match self.q { Calidad::Rapida => "½ rápida", Calidad::Completa => "1× completa", Calidad::Exacta => "1× exacta (ss2+gauss)" }).show_ui(ui, |ui| {
                    ui.selectable_value(&mut self.q, Calidad::Rapida, "½ rápida");
                    ui.selectable_value(&mut self.q, Calidad::Completa, "1× completa");
                    ui.selectable_value(&mut self.q, Calidad::Exacta, "1× exacta (ss2+gauss)");
                });
                if q0 != self.q { self.invalidar(); }
                if ui.button("Reiniciar ediciones").clicked() { self.estado.ediciones.clear(); self.invalidar(); }
                ui.separator();
                ui.label(format!("render: {:.0} ms", self.ultimo_ms));
                ui.weak(format!("{} · ediciones solo en memoria (no se escribe al .xstage/.tvg)", self.frames[self.cur].nombre));
            });
        });
        egui::Panel::bottom("timeline").show(ui, |ui| {
            ui.horizontal(|ui| {
                if ui.button("⏮").clicked() { self.cur = 0; }
                if ui.button(if self.playing { "⏸" } else { "▶" }).clicked() { self.playing = !self.playing; self.t_play = Instant::now(); }
                if ui.button("⏭").clicked() { self.cur = self.frames.len() - 1; }
                ui.add(egui::DragValue::new(&mut self.fps).range(1.0..=60.0).suffix(" fps"));
                ui.label(format!("fotograma {} ({}/{})", self.frames[self.cur].fotograma, self.cur + 1, self.frames.len()));
            });
            let n = self.frames.len();
            let (rect, resp) = ui.allocate_exact_size(egui::vec2(ui.available_width(), 38.0), egui::Sense::click_and_drag());
            if (resp.dragged() || resp.clicked()) && resp.interact_pointer_pos().is_some() {
                let x = resp.interact_pointer_pos().unwrap().x;
                self.cur = (((x - rect.left()) / rect.width() * n as f32).floor() as isize).clamp(0, n as isize - 1) as usize;
            }
            let p = ui.painter_at(rect);
            p.rect_filled(rect, 3.0, egui::Color32::from_gray(28));
            let w = rect.width() / n as f32;
            for i in 0..n {
                let r = egui::Rect::from_min_size(rect.min + egui::vec2(w * i as f32, 0.0), egui::vec2(w, rect.height()));
                if i == self.cur { p.rect_filled(r.shrink(1.0), 2.0, egui::Color32::from_rgb(70, 120, 200)); }
                if w > 14.0 || i % 5 == 0 || i == self.cur {
                    p.text(r.center_top() + egui::vec2(0.0, 3.0), egui::Align2::CENTER_TOP, self.frames[i].fotograma.to_string(), egui::FontId::proportional(11.0), egui::Color32::from_gray(210));
                }
                p.line_segment([r.left_bottom(), r.left_bottom() - egui::vec2(0.0, 8.0)], egui::Stroke::new(1.0, egui::Color32::from_gray(90)));
            }
        });
        // ---- CAPAS -------------------------------------------------------------------------
        egui::Panel::left("capas").default_size(360.0).show(ui, |ui| {
            ui.heading("Capas");
            ui.horizontal(|ui| {
                ui.label("filtro");
                ui.text_edit_singleline(&mut self.filtro);
            });
            ui.horizontal(|ui| {
                if ui.small_button("Mostrar todas").clicked() { self.estado.ocultas.clear(); self.invalidar(); }
                if ui.small_button("Ocultar todas").clicked() {
                    self.estado.ocultas = self.frames[self.cur].piezas.iter().map(|p| p.key.clone()).collect();
                    self.invalidar();
                }
                ui.weak(format!("{} ocultas", self.estado.ocultas.len()));
            });
            ui.weak("de adelante (arriba) hacia atrás; ● = visible");
            let f = self.filtro.to_lowercase();
            let idxs: Vec<usize> = (0..self.frames[self.cur].piezas.len()).rev().filter(|&i| f.is_empty() || self.frames[self.cur].piezas[i].key.to_lowercase().contains(&f)).collect();
            let mut cambio = false;
            let mut nueva_sel = None;
            egui::ScrollArea::vertical().auto_shrink([false, false]).show_rows(ui, 20.0, idxs.len(), |ui, rango| {
                for k in rango {
                    let i = idxs[k];
                    let p = &self.frames[self.cur].piezas[i];
                    ui.horizontal(|ui| {
                        let mut vis = !self.estado.ocultas.contains(&p.key);
                        if ui.checkbox(&mut vis, "").changed() {
                            if vis { self.estado.ocultas.remove(&p.key); } else { self.estado.ocultas.insert(p.key.clone()); }
                            cambio = true;
                        }
                        let (nombre, grupo) = p.id.rsplit_once('/').map(|(g, n)| (n, g)).unwrap_or((p.id.as_str(), ""));
                        let editada = self.estado.ediciones.contains_key(&p.key);
                        let txt = format!("{:>3} {}{}{}", p.orden, nombre, if editada { " ✎" } else { "" }, if p.recorte.is_empty() { "" } else { " ✂" });
                        let r = ui.selectable_label(self.sel.as_deref() == Some(p.key.as_str()), txt).on_hover_text(format!(
                            "{}\norden {} · razón: {} · puertos {:?} · z {:.4}\ngrupo: {}{}", p.id, p.orden, p.razon, p.puertos, p.z, grupo,
                            if p.recorte.is_empty() { String::new() } else { format!("\ncutters: {}", p.recorte.iter().map(|c| c.nodo.rsplit('/').next().unwrap_or("").to_string()).collect::<Vec<_>>().join(", ")) }));
                        if r.clicked() { nueva_sel = Some(p.key.clone()); }
                        ui.weak(grupo.rsplit('/').next().unwrap_or(""));
                    });
                }
            });
            if cambio { self.invalidar(); }
            if let Some(k) = nueva_sel { self.sel = Some(k); self.sincronizar_nodos(); }
        });
        // ---- PARAMETROS --------------------------------------------------------------------
        egui::Panel::right("params").default_size(300.0).show(ui, |ui| {
            ui.heading("Parámetros");
            let Some(key) = self.sel.clone() else { ui.label("Selecciona una capa."); return };
            let Some(p) = self.frames[self.cur].piezas.iter().find(|p| p.key == key) else { ui.label("(la pieza no está en este fotograma)"); return };
            ui.strong(p.id.rsplit('/').next().unwrap_or(""));
            ui.weak(p.id.clone());
            ui.label(format!("orden {} · razón: {}", p.orden, p.razon));
            ui.label(format!("puertos {:?} · z {:.4}", p.puertos, p.z));
            ui.label(format!("dibujo {}", p.dibujo));
            if !p.recorte.is_empty() {
                ui.label(format!("cutters: {}", p.recorte.iter().map(|c| format!("{}{}", c.nodo.rsplit('/').next().unwrap_or(""), if c.inv { " (inv)" } else { "" })).collect::<Vec<_>>().join(", ")));
            }
            ui.separator();
            ui.label(format!("matriz_campo base: [[{:.3} {:.3} {:.3}] [{:.3} {:.3} {:.3}]]", p.m[0][0], p.m[0][1], p.m[0][2], p.m[1][0], p.m[1][1], p.m[1][2]));
            let mut ed = self.estado.ediciones.get(&key).copied().unwrap_or_default();
            let antes = ed;
            egui::Grid::new("g").num_columns(2).show(ui, |ui| {
                ui.label("offset X (campos)"); ui.add(egui::DragValue::new(&mut ed.dx).speed(0.02)); ui.end_row();
                ui.label("offset Y (campos)"); ui.add(egui::DragValue::new(&mut ed.dy).speed(0.02)); ui.end_row();
                ui.label("rotación (°)"); ui.add(egui::DragValue::new(&mut ed.rot).speed(0.5)); ui.end_row();
                ui.label("escala X"); ui.add(egui::DragValue::new(&mut ed.esc).speed(0.01)); ui.end_row();
                ui.label("escala Y"); ui.add(egui::DragValue::new(&mut ed.escy).speed(0.01)); ui.end_row();
                ui.label("opacidad"); ui.add(egui::Slider::new(&mut ed.op, 0.0..=1.0)); ui.end_row();
            });
            if ui.button("Reiniciar esta pieza").clicked() { ed = Edit::default(); }
            ui.weak("rotación/escala sobre el origen de la pieza; offset en campos de Harmony.");
            if ed != antes {
                if ed == Edit::default() { self.estado.ediciones.remove(&key); } else { self.estado.ediciones.insert(key, ed); }
                self.invalidar();
            }
        });
        // ---- PLAYER ------------------------------------------------------------------------
        egui::CentralPanel::default().show(ui, |ui| {
            let tex = self.textura(&ctx);
            let tam = self.frames[self.cur].tam;
            let avail = ui.available_rect_before_wrap();
            let esc = (avail.width() / tam.0 as f32).min(avail.height() / tam.1 as f32);
            let r = egui::Rect::from_center_size(avail.center(), egui::vec2(tam.0 as f32 * esc, tam.1 as f32 * esc));
            if let Some(t) = tex {
                ui.painter().image(t.id(), r, egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0)), egui::Color32::WHITE);
            }
            if let Some(k) = self.sel.clone() {
                if let Some(i) = self.frames[self.cur].piezas.iter().position(|p| p.key == k) {
                    if let Some(c) = render::caja(&self.frames[self.cur], &mut self.cache, i, &self.estado) {
                        let rb = egui::Rect::from_min_max(r.min + egui::vec2(c[0] * r.width(), c[1] * r.height()), r.min + egui::vec2(c[2] * r.width(), c[3] * r.height()));
                        ui.painter().rect_stroke(rb.intersect(r), 0.0, egui::Stroke::new(2.0, egui::Color32::from_rgb(255, 220, 90)), egui::StrokeKind::Outside);
                    }
                }
            }
        });
        // ---- NODOS (ventana flotante) -----------------------------------------------------
        if self.nodos_abierto {
            let mut abierto = true;
            let tam = if self.nodos_grande { [1150.0, 640.0] } else { [760.0, 480.0] };
            let mut pulsado = None;
            egui::Window::new("Nodos").open(&mut abierto).default_size(tam).default_pos([if self.nodos_grande { 380.0 } else { 420.0 }, 70.0]).show(&ctx, |ui| {
                match &self.grafo {
                    Some(g) => pulsado = nodos::mostrar(ui, g, &mut self.vista),
                    None => { ui.label("Sin grafo: genera <datos de trabajo omitidos> con scripts\\grafo_visor.py"); }
                }
            });
            self.nodos_abierto = abierto;
            if let Some(id) = pulsado {
                if let Some(p) = self.frames[self.cur].piezas.iter().rev().find(|p| p.id == id) { self.sel = Some(p.key.clone()); }
            }
        }
        let _ = &self.msg;
        let _ = &self.log_ms;
    }
}

// ================= ventana + wgpu =================
struct Gpu {
    surface: wgpu::Surface<'static>,
    device: wgpu::Device,
    queue: wgpu::Queue,
    config: wgpu::SurfaceConfiguration,
    egui_render: egui_wgpu::Renderer,
    estado: egui_winit::State,
}
struct App {
    opts: Opciones,
    visor: Visor,
    win: Option<Arc<Window>>,
    gpu: Option<Gpu>,
    ctx: egui::Context,
    frames: u32,
    salir: bool,
}

impl App {
    fn dibujar(&mut self) {
        let (Some(win), Some(g)) = (self.win.clone(), self.gpu.as_mut()) else { return };
        self.frames += 1;
        let entrada = g.estado.take_egui_input(&win);
        let visor = &mut self.visor;
        let salida = self.ctx.run_ui(entrada, |ui| visor.ui(ui));
        g.estado.handle_platform_output(&win, salida.platform_output);
        let prim = self.ctx.tessellate(salida.shapes, salida.pixels_per_point);
        use wgpu::CurrentSurfaceTexture as Cst;
        let frame = match g.surface.get_current_texture() {
            Cst::Success(f) | Cst::Suboptimal(f) => f,
            Cst::Outdated => { g.surface.configure(&g.device, &g.config); win.request_redraw(); return }
            _ => { win.request_redraw(); return }
        };
        let vista = frame.texture.create_view(&wgpu::TextureViewDescriptor::default());
        let mut enc = g.device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("frame") });
        let pant = egui_wgpu::ScreenDescriptor { size_in_pixels: [g.config.width, g.config.height], pixels_per_point: salida.pixels_per_point };
        for (id, delta) in &salida.textures_delta.set { g.egui_render.update_texture(&g.device, &g.queue, *id, delta); }
        let previos = g.egui_render.update_buffers(&g.device, &g.queue, &mut enc, &prim, &pant);
        {
            let mut pass = enc.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("egui"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &vista, depth_slice: None, resolve_target: None,
                    ops: wgpu::Operations { load: wgpu::LoadOp::Clear(wgpu::Color { r: 0.1, g: 0.1, b: 0.11, a: 1.0 }), store: wgpu::StoreOp::Store },
                })],
                depth_stencil_attachment: None, timestamp_writes: None, occlusion_query_set: None, multiview_mask: None,
            }).forget_lifetime();
            g.egui_render.render(&mut pass, &prim, &pant);
        }
        for id in &salida.textures_delta.free { g.egui_render.free_texture(id); }
        // captura (modo --screenshot): tras ~60 cuadros, copia la superficie a un buffer y la guarda como PNG
        let capturar = self.opts.shot.is_some() && self.frames >= 60;
        let (w, h) = (g.config.width, g.config.height);
        let bpr = (w * 4 + 255) / 256 * 256;
        let buf = if capturar {
            let b = g.device.create_buffer(&wgpu::BufferDescriptor { label: Some("shot"), size: (bpr * h) as u64, usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ, mapped_at_creation: false });
            enc.copy_texture_to_buffer(
                wgpu::TexelCopyTextureInfo { texture: &frame.texture, mip_level: 0, origin: wgpu::Origin3d::ZERO, aspect: wgpu::TextureAspect::All },
                wgpu::TexelCopyBufferInfo { buffer: &b, layout: wgpu::TexelCopyBufferLayout { offset: 0, bytes_per_row: Some(bpr), rows_per_image: Some(h) } },
                wgpu::Extent3d { width: w, height: h, depth_or_array_layers: 1 },
            );
            Some(b)
        } else { None };
        g.queue.submit(previos.into_iter().chain([enc.finish()]));
        if let Some(b) = buf {
            let sl = b.slice(..);
            sl.map_async(wgpu::MapMode::Read, |_| {});
            let _ = g.device.poll(wgpu::PollType::wait_indefinitely());
            let datos = sl.get_mapped_range();
            let bgra = matches!(g.config.format, wgpu::TextureFormat::Bgra8Unorm | wgpu::TextureFormat::Bgra8UnormSrgb);
            let mut pm = tiny_skia::Pixmap::new(w, h).unwrap();
            let od = pm.data_mut();
            for y in 0..h as usize {
                for x in 0..w as usize {
                    let s = y * bpr as usize + x * 4;
                    let d = (y * w as usize + x) * 4;
                    let (r, gg, bb) = if bgra { (datos[s + 2], datos[s + 1], datos[s]) } else { (datos[s], datos[s + 1], datos[s + 2]) };
                    od[d] = r; od[d + 1] = gg; od[d + 2] = bb; od[d + 3] = 255;
                }
            }
            drop(datos);
            let ruta = self.opts.shot.clone().unwrap();
            if let Some(p) = ruta.parent() { let _ = std::fs::create_dir_all(p); }
            pm.save_png(&ruta).expect("png");
            eprintln!("captura -> {:?} ({}x{}), render {:.0} ms", ruta, w, h, self.visor.ultimo_ms);
            self.salir = true;
        }
        frame.present();
        let rd = salida.viewport_output.get(&egui::ViewportId::ROOT).map(|v| v.repaint_delay);
        if self.opts.shot.is_some() || rd == Some(std::time::Duration::ZERO) { win.request_redraw(); }
    }
}

impl ApplicationHandler for App {
    fn resumed(&mut self, el: &ActiveEventLoop) {
        if self.win.is_some() { return; }
        let win = Arc::new(el.create_window(Window::default_attributes().with_title("pegcraft-viewer (spike)").with_inner_size(PhysicalSize::new(self.opts.tam.0, self.opts.tam.1))).expect("ventana"));
        let instance = wgpu::Instance::default();
        let surface = instance.create_surface(win.clone()).expect("superficie");
        let adapter = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions { power_preference: wgpu::PowerPreference::HighPerformance, compatible_surface: Some(&surface), force_fallback_adapter: false })).expect("adaptador");
        eprintln!("[gpu] {}", adapter.get_info().name);
        let (device, queue) = pollster::block_on(adapter.request_device(&wgpu::DeviceDescriptor::default())).expect("device");
        let caps = surface.get_capabilities(&adapter);
        let format = caps.formats.iter().copied().find(|f| !f.is_srgb()).unwrap_or(caps.formats[0]);
        let tam = win.inner_size();
        let config = wgpu::SurfaceConfiguration {
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC, format, width: tam.width.max(1), height: tam.height.max(1),
            present_mode: wgpu::PresentMode::AutoVsync, desired_maximum_frame_latency: 2, alpha_mode: caps.alpha_modes[0], view_formats: vec![],
        };
        surface.configure(&device, &config);
        let egui_render = egui_wgpu::Renderer::new(&device, format, egui_wgpu::RendererOptions::default());
        self.ctx.set_theme(egui::Theme::Dark);
        let estado = egui_winit::State::new(self.ctx.clone(), egui::ViewportId::ROOT, &*win, Some(win.scale_factor() as f32), Some(winit::window::Theme::Dark), Some(device.limits().max_texture_dimension_2d as usize));
        self.gpu = Some(Gpu { surface, device, queue, config, egui_render, estado });
        win.request_redraw();
        self.win = Some(win);
    }
    fn window_event(&mut self, el: &ActiveEventLoop, _id: WindowId, ev: WindowEvent) {
        if let (Some(win), Some(g)) = (self.win.clone(), self.gpu.as_mut()) {
            let r = g.estado.on_window_event(&win, &ev);
            if r.repaint { win.request_redraw(); }
        }
        match ev {
            WindowEvent::CloseRequested => el.exit(),
            WindowEvent::Resized(t) => {
                if let Some(g) = self.gpu.as_mut() {
                    g.config.width = t.width.max(1);
                    g.config.height = t.height.max(1);
                    g.surface.configure(&g.device, &g.config);
                }
                if let Some(w) = &self.win { w.request_redraw(); }
            }
            WindowEvent::RedrawRequested => {
                self.dibujar();
                if self.salir { el.exit(); }
            }
            _ => {}
        }
    }
}

fn medir(o: &Opciones) {
    let mut v = Visor::nuevo(o).expect("cargar");
    let n = v.frames.len();
    println!("{} fotogramas, {} piezas en el primero", n, v.frames[0].piezas.len());
    for q in [Calidad::Rapida, Calidad::Completa, Calidad::Exacta] {
        let _ = render::render(&v.frames[0], &mut v.cache, &v.estado, q); // calienta la cache de SVG
        let t = Instant::now();
        for f in &v.frames { let _ = render::render(f, &mut v.cache, &v.estado, q); }
        println!("{:?}: {:.0} ms/fotograma (cache SVG caliente)", q, t.elapsed().as_secs_f32() * 1000.0 / n as f32);
    }
    let t = Instant::now();
    let mut c2 = Cache::default();
    let _ = render::render(&v.frames[0], &mut c2, &v.estado, Calidad::Rapida);
    println!("primera carga (parseo de SVG + render ½): {:.0} ms", t.elapsed().as_secs_f32() * 1000.0);
    // ocultar una capa / editar un parametro
    let k = v.frames[0].piezas[v.frames[0].piezas.len() / 2].key.clone();
    for q in [Calidad::Rapida, Calidad::Completa] {
        v.estado.ocultas.insert(k.clone());
        let t = Instant::now();
        let _ = render::render(&v.frames[0], &mut v.cache, &v.estado, q);
        println!("{:?}: re-render tras ocultar 1 capa: {:.0} ms", q, t.elapsed().as_secs_f32() * 1000.0);
        v.estado.ocultas.clear();
        v.estado.ediciones.insert(k.clone(), Edit { dx: 0.3, rot: 10.0, op: 0.6, ..Edit::default() });
        let t = Instant::now();
        let _ = render::render(&v.frames[0], &mut v.cache, &v.estado, q);
        println!("{:?}: re-render tras editar (dx, rot, opacidad): {:.0} ms", q, t.elapsed().as_secs_f32() * 1000.0);
        v.estado.ediciones.clear();
    }
}

fn main() {
    let o = args();
    if o.medir { medir(&o); return; }
    let visor = match Visor::nuevo(&o) { Ok(v) => v, Err(e) => { eprintln!("error: {e}"); std::process::exit(1) } };
    let el = EventLoop::new().expect("event loop");
    el.set_control_flow(ControlFlow::Wait);
    let mut app = App { opts: o, visor, win: None, gpu: None, ctx: egui::Context::default(), frames: 0, salir: false };
    el.run_app(&mut app).expect("run");
}
