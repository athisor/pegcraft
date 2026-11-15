// pegcraft-viewer-craft: el visor alineado con la familia Craft (eframe 0.37 + fork storytold/egui + craft-ui por git, mismas revs que FilmCraft).
// Misma logica que ../pegcraft-viewer (spike sobre egui 0.35 crates.io + bucle propio); aqui los paneles van en el docking de craft-ui
// (patron de craft-libs/crates/ui/examples/docking_native.rs y del dock.rs de cada Craft: un enum de paneles + un Layout).
// SOLO LECTURA sobre el horneado: las ediciones viven en memoria y nunca se escriben al .xstage ni a los .tvg.
// App de ventana en release: sin consola propia al abrir con doble clic o Start-Process. Desde una consola se re-engancha a la del padre (adjuntar_consola)
// para que --medir, --screenshot, --comparar-gpu y --analizar sigan imprimiendo.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod abrir;
mod analizar;
mod iconos;
use iconos::Icono;
mod nodos;
mod comparar_gpu;
mod render;
mod render_gpu;

use craft_ui::docking::{Action, DockArea, DockContent, DockStyle, Layout, Node};
use std::collections::HashSet;

/// herramientas de la barra lateral (actuan sobre la pieza seleccionada, en el player)
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum Herr {
    Seleccionar,
    Mover,
    Rotar,
    Escalar,
}
type Snap = (HashSet<String>, HashMap<String, Edit>);
const PANELES: [Panel; 5] = [Panel::Capas, Panel::Player, Panel::Nodos, Panel::Timeline, Panel::Parametros];
const ESPACIOS: [&str; 3] = ["Estándar", "Nodos grande", "Revisión (player)"];
use craft_ui::layout::{SplitAxis, SplitSize};
use render::{Cache, Calidad, Edit, Escena, Estado};
use std::{collections::HashMap, path::PathBuf, time::Instant};

#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
enum Panel {
    Capas,
    Player,
    Nodos,
    Timeline,
    Parametros,
}
impl Panel {
    fn nombre(self) -> &'static str {
        match self {
            Panel::Capas => "Capas",
            Panel::Player => "Player",
            Panel::Nodos => "Nodos",
            Panel::Timeline => "Línea de tiempo",
            Panel::Parametros => "Parámetros",
        }
    }
}

/// espacios de trabajo. Estándar: Capas | (Player sobre Timeline) | (Nodos sobre Parametros).
/// Nodos grande y Revisión: Capas | ((Player sobre Nodos) sobre Timeline) | Parametros.
fn espacio(kind: usize) -> Layout<Panel> {
    let tabs = |p: Panel| Node::Tabs { panels: vec![p], active: 0 };
    let split = |axis, r: f32, a: Node<Panel>, b: Node<Panel>| Node::Split { axis, size: SplitSize::Ratio(r), first: Box::new(a), second: Box::new(b) };
    if kind == 0 {
        let centro = split(SplitAxis::Vertical, 0.83, tabs(Panel::Player), tabs(Panel::Timeline));
        let der = split(SplitAxis::Vertical, 0.50, tabs(Panel::Nodos), tabs(Panel::Parametros));
        let resto = split(SplitAxis::Horizontal, 0.82, centro, der);
        return Layout { root: Some(split(SplitAxis::Horizontal, 0.14, tabs(Panel::Capas), resto)), floating: vec![] };
    }
    let medio = match kind {
        2 => tabs(Panel::Player), // revision: solo el player (Nodos se abre desde Ventanas)
        _ => split(SplitAxis::Vertical, if kind == 1 { 0.12 } else { 0.55 }, tabs(Panel::Player), tabs(Panel::Nodos)),
    };
    let centro = split(SplitAxis::Vertical, 0.72, medio, tabs(Panel::Timeline));
    let der = split(SplitAxis::Horizontal, 0.80, centro, tabs(Panel::Parametros));
    Layout { root: Some(split(SplitAxis::Horizontal, 0.22, tabs(Panel::Capas), der)), floating: vec![] }
}

struct Opciones {
    ruta: PathBuf,
    grafo: Option<PathBuf>,
    shot: Option<PathBuf>,
    frame: usize,
    ocultar: Vec<String>,
    editar: Vec<String>,
    seleccionar: Option<String>,
    calidad: Calidad,
    medir: bool,
    tam: (f32, f32),
    nodos_grande: bool,
    abrir: Option<(String, u32, u32)>, // --abrir X.xstage --frames A:B : lanza el horneado al arrancar (prueba del flujo de «Abrir escena»)
    grupo: Option<String>, // --grupo Top/ch_rig : la vista de nodos arranca dentro de ese grupo
    gpu: bool, // --gpu : arranca con «Acelerar por GPU» marcada (con --medir, mide por GPU)
    comparar: Option<(PathBuf, Vec<usize>)>, // --comparar-gpu SALIDA [--cuadros 9,59,109] : GPU vs CPU Completa, cifras y láminas PNG
    analizar: Option<String>, // --analizar CARPETA : abre «Analizar carpeta de planos» con esa carpeta ya listada (con --analizar-correr, también lanza el análisis; --log-analisis DIR)
    analizar_correr: bool,
    analizar_compartible: bool,
    log_analisis: Option<String>,
    ruta_explicita: bool, // se pasó una carpeta/archivo horneado en la línea de comandos
}

fn args() -> Opciones {
    let a: Vec<String> = std::env::args().skip(1).collect();
    let mut o = Opciones {
        ruta: abrir::entorno().trabajo.join("horneado"),
        grafo: None, shot: None, frame: 0, ocultar: vec![], editar: vec![], seleccionar: None, calidad: Calidad::Rapida, medir: false, tam: (1600.0, 900.0), nodos_grande: false, abrir: None, grupo: None, gpu: false, comparar: None, analizar: None, analizar_correr: false, analizar_compartible: false, log_analisis: None, ruta_explicita: false,
    };
    let mut rango = (1u32, 1u32);
    let mut cuadros: Vec<usize> = vec![];
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
            "--nodos-grande" => o.nodos_grande = true,
            "--grupo" => { o.grupo = Some(sig(i)); i += 1 }
            "--abrir" => { o.abrir = Some((sig(i), 1, 1)); i += 1 }
            "--frames" => { if let Some((a, b)) = sig(i).split_once(':') { rango = (a.parse().unwrap_or(1), b.parse().unwrap_or(1)); } i += 1 }
            "--medir" => o.medir = true,
            "--gpu" => o.gpu = true,
            "--analizar" => { o.analizar = Some(sig(i)); i += 1 }
            "--analizar-correr" => o.analizar_correr = true,
            "--analizar-compartible" => o.analizar_compartible = true,
            "--log-analisis" => { o.log_analisis = Some(sig(i)); i += 1 }
            "--comparar-gpu" => { o.comparar = Some((sig(i).into(), vec![])); i += 1 }
            "--cuadros" => { cuadros = sig(i).split(',').filter_map(|s| s.trim().parse().ok()).collect(); i += 1 }
            "--calidad" => { o.calidad = match sig(i).as_str() { "completa" => Calidad::Completa, "exacta" => Calidad::Exacta, _ => Calidad::Rapida }; i += 1 }
            "--tam" => { if let Some((w, h)) = sig(i).split_once('x') { o.tam = (w.parse().unwrap_or(1600.0), h.parse().unwrap_or(900.0)); } i += 1 }
            s if !s.starts_with("--") => { o.ruta = s.into(); o.ruta_explicita = true }
            _ => {}
        }
        i += 1;
    }
    if let Some(a) = o.abrir.as_mut() { a.1 = rango.0; a.2 = rango.1; }
    if let Some(c) = o.comparar.as_mut() { c.1 = cuadros; }
    if o.grafo.is_none() {
        let d = abrir::entorno().trabajo.join("visor").join("grafo.json");
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
    if v.is_empty() {
        // salida de «Abrir escena»: una subcarpeta por fotograma (f0001\escena.json, f0002\escena.json, ...), cada una con sus dibujos
        let mut sub: Vec<PathBuf> = std::fs::read_dir(ruta).map(|d| d.filter_map(|e| e.ok()).map(|e| e.path().join("escena.json")).filter(|p| p.is_file()).collect()).unwrap_or_default();
        sub.sort();
        v = sub;
    }
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
    sel: Option<String>,
    filtro: String,
    q: Calidad,
    texs: HashMap<usize, egui::TextureHandle>,
    ultimo_ms: f32,
    grafo: Option<nodos::Grafo>,
    vista: nodos::Vista,
    herr: Herr,
    hist: Vec<Snap>,
    rehacer: Vec<Snap>,
    prev: Snap,
    t_hist: Instant,
    espacio: usize,
    dlg: abrir::Dialogo,
    ana: analizar::Analisis,             // Archivo > Analizar carpeta de planos…
    gpu_on: bool,                       // casilla «Acelerar por GPU»
    gpu: Option<render_gpu::Gpu>,        // se crea al primer uso (0,4 s); None si no hay GPU o falló
    gpu_aviso: Option<String>,           // por qué se cayó a CPU (visible en la barra)
    gpu_prueba: Option<String>,          // diagnóstico de la última pasada por GPU (adaptador)
}

impl Visor {
    fn gpu_fallo(&mut self, e: String) {
        eprintln!("GPU: {e}");
        self.gpu_aviso = Some(format!("GPU no disponible, dibujando en CPU: {e}"));
        self.gpu_on = false;
        self.gpu = None;
    }
    /// dibuja el fotograma `i` con la calidad actual: GPU si la casilla está marcada y la calidad lo permite (Exacta siempre CPU); si la GPU falla, CPU con aviso
    fn dibujar(&mut self, i: usize) -> tiny_skia::Pixmap {
        if self.gpu_on && self.q != Calidad::Exacta {
            if self.gpu.is_none() {
                match render_gpu::Gpu::nuevo() {
                    Ok(g) => { self.gpu_prueba = Some(format!("{} (init {:.0} ms)", g.adaptador, g.init_ms)); self.gpu = Some(g) }
                    Err(e) => self.gpu_fallo(e),
                }
            }
            if let Some(g) = self.gpu.as_mut() {
                match g.render(&self.frames[i], &self.estado, self.q, true) {
                    Ok(pm) => return pm,
                    Err(e) => self.gpu_fallo(e),
                }
            }
        }
        render::render(&self.frames[i], &mut self.cache, &self.estado, self.q)
    }
    fn poner_gpu(&mut self, on: bool) {
        self.gpu_on = on;
        if on { self.gpu_aviso = None; }
        self.invalidar();
    }
    /// reemplaza la escena cargada por la de una carpeta horneada (y su grafo); reinicia ediciones, historial y cachés
    fn cargar_carpeta(&mut self, ruta: &std::path::Path, grafo: Option<PathBuf>) -> Result<(), String> {
        let rutas = descubrir(ruta);
        if rutas.is_empty() { return Err(format!("no hay escena horneada en {}", ruta.display())); }
        let mut frames: Vec<Escena> = rutas.iter().map(|r| render::cargar(r)).collect::<Result<_, _>>()?;
        frames.sort_by_key(|f| f.fotograma);
        let grafo = grafo.and_then(|g| nodos::cargar(&g).map_err(|e| eprintln!("grafo: {e}")).ok());
        let raiz = grafo.as_ref().map(|g| g.raiz.clone()).unwrap_or("Top".into());
        self.frames = frames;
        self.cur = 0;
        self.playing = false;
        self.estado = Estado::default();
        self.sel = None;
        self.hist.clear();
        self.rehacer.clear();
        self.prev = (HashSet::new(), HashMap::new());
        self.cache = Cache::default();
        if let Some(g) = self.gpu.as_mut() { g.vaciar_cache(); }
        self.texs.clear();
        self.vista = nodos::Vista::nueva(&raiz);
        self.grafo = grafo;
        Ok(())
    }
    /// deshacer/rehacer por instantaneas del estado editable (ocultas + ediciones); se registran solas al cambiar el estado (ver App::ui)
    fn registrar(&mut self) {
        if self.estado.ocultas != self.prev.0 || self.estado.ediciones != self.prev.1 {
            if self.hist.is_empty() || self.t_hist.elapsed().as_millis() > 400 {
                self.hist.push(self.prev.clone());
                if self.hist.len() > 200 { self.hist.remove(0); }
            }
            self.rehacer.clear();
            self.t_hist = Instant::now();
            self.prev = (self.estado.ocultas.clone(), self.estado.ediciones.clone());
        }
    }
    fn deshacer(&mut self) {
        if let Some(s) = self.hist.pop() {
            self.rehacer.push(self.prev.clone());
            self.estado.ocultas = s.0.clone();
            self.estado.ediciones = s.1.clone();
            self.prev = s;
            self.invalidar();
        }
    }
    fn rehacer_(&mut self) {
        if let Some(s) = self.rehacer.pop() {
            self.hist.push(self.prev.clone());
            self.estado.ocultas = s.0.clone();
            self.estado.ediciones = s.1.clone();
            self.prev = s;
            self.invalidar();
        }
    }
    /// pieza visible mas al frente cuya caja contiene el punto (fracciones del cuadro); prefiere cajas que no cubren casi todo el cuadro
    fn recoger(&mut self, f: (f32, f32)) -> Option<String> {
        let n = self.frames[self.cur].piezas.len();
        let mut mejor = None;
        for i in (0..n).rev() {
            let key = self.frames[self.cur].piezas[i].key.clone();
            if self.estado.ocultas.contains(&key) { continue; }
            if let Some(c) = render::caja(&self.frames[self.cur], &mut self.cache, i, &self.estado) {
                if f.0 >= c[0] && f.0 <= c[2] && f.1 >= c[1] && f.1 <= c[3] {
                    if (c[2] - c[0]) * (c[3] - c[1]) < 0.6 { return Some(key); }
                    if mejor.is_none() { mejor = Some(key); }
                }
            }
        }
        mejor
    }
    fn nuevo(o: &Opciones) -> Result<Self, String> {
        let rutas = descubrir(&o.ruta);
        // Sin ruta pedida y sin nada horneado (primer arranque, p. ej. doble clic en el paquete): visor vacío con el diálogo «Abrir escena» a la vista.
        let vacio = rutas.is_empty() && !o.ruta_explicita;
        if rutas.is_empty() && !vacio { return Err(format!("no hay escenas en {:?}", o.ruta)); }
        let frames: Vec<Escena> = if vacio {
            vec![Escena { nombre: "(sin escena)".into(), fotograma: 1, tam: (1920, 1080), cam: (0.0, 0.0, 1.0, 1.0, 1.0), base: PathBuf::new(), piezas: vec![] }]
        } else {
            rutas.iter().map(|r| render::cargar(r)).collect::<Result<_, _>>()?
        };
        let grafo = o.grafo.as_ref().and_then(|g| nodos::cargar(g).map_err(|e| eprintln!("grafo: {e}")).ok());
        let raiz = grafo.as_ref().map(|g| g.raiz.clone()).unwrap_or("Top".into());
        let mut v = Visor {
            cur: o.frame.min(frames.len() - 1), frames, playing: false, t_play: Instant::now(), fps: 24.0, cache: Cache::default(), estado: Estado::default(),
            sel: None, filtro: String::new(), q: o.calidad, texs: HashMap::new(), ultimo_ms: 0.0, grafo, vista: nodos::Vista::nueva(&raiz),
            herr: Herr::Seleccionar, hist: vec![], rehacer: vec![], prev: (HashSet::new(), HashMap::new()), t_hist: Instant::now(), espacio: if o.nodos_grande { 1 } else { 0 }, dlg: abrir::Dialogo::default(), ana: analizar::Analisis::default(),
            gpu_on: o.gpu, gpu: None, gpu_aviso: None, gpu_prueba: None,
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
        v.prev = (v.estado.ocultas.clone(), v.estado.ediciones.clone());
        if vacio { v.dlg.abierto = true; }
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
    fn invalidar(&mut self) { self.texs.clear(); }
    fn textura(&mut self, ctx: &egui::Context) -> Option<egui::TextureHandle> {
        if !self.texs.contains_key(&self.cur) {
            let t0 = Instant::now();
            let pm = self.dibujar(self.cur);
            self.ultimo_ms = t0.elapsed().as_secs_f32() * 1000.0;
            let img = egui::ColorImage::from_rgba_premultiplied([pm.width() as usize, pm.height() as usize], pm.data());
            self.texs.insert(self.cur, ctx.load_texture(format!("cuadro{}", self.cur), img, egui::TextureOptions::LINEAR));
        }
        self.texs.get(&self.cur).cloned()
    }

    /// barra de herramientas (bajo el menu): transporte, deshacer/rehacer, calidad. El selector de espacio de trabajo lo pone App::ui (necesita el Layout).
    fn ui_barra(&mut self, ui: &mut egui::Ui) {
        ui.horizontal(|ui| {
            if iconos::boton(ui, Icono::Deshacer, false, !self.hist.is_empty(), 28.0, "Deshacer (Ctrl+Z)").clicked() { self.deshacer(); }
            if iconos::boton(ui, Icono::Rehacer, false, !self.rehacer.is_empty(), 28.0, "Rehacer (Ctrl+Y)").clicked() { self.rehacer_(); }
            ui.separator();
            if iconos::boton(ui, Icono::Inicio, false, true, 28.0, "Primer fotograma").clicked() { self.cur = 0; }
            if iconos::boton(ui, if self.playing { Icono::Pausa } else { Icono::Play }, self.playing, true, 28.0, "Reproducir / pausa").clicked() { self.playing = !self.playing; self.t_play = Instant::now(); }
            if iconos::boton(ui, Icono::Fin, false, true, 28.0, "Último fotograma").clicked() { self.cur = self.frames.len() - 1; }
            ui.separator();
            let q0 = self.q;
            egui::ComboBox::from_id_salt("calidad").selected_text(match self.q { Calidad::Rapida => "½ rápida", Calidad::Completa => "1× completa", Calidad::Exacta => "1× exacta (ss2+gauss)" }).show_ui(ui, |ui| {
                ui.selectable_value(&mut self.q, Calidad::Rapida, "½ rápida");
                ui.selectable_value(&mut self.q, Calidad::Completa, "1× completa");
                ui.selectable_value(&mut self.q, Calidad::Exacta, "1× exacta (ss2+gauss)");
            });
            if q0 != self.q { self.invalidar(); }
            let mut on = self.gpu_on;
            let r = ui.checkbox(&mut on, "Acelerar por GPU").on_hover_text(
                "Dibuja cada fotograma con vello sobre la GPU (decenas de veces más rápido que la CPU).\n\
                 Calidad «exacta» se queda en CPU (es la referencia contra Harmony).\n\
                 Diferencias con la CPU: el antialias de bordes no es idéntico (vello vs tiny-skia) y la GPU sí dibuja degradados (la CPU los ignora).\n\
                 Ninguno de los dos hace aún la mezcla aditiva «glow suma» ni difumina los mattes.\n\
                 Si la GPU falla, vuelve a CPU y lo avisa aquí.");
            if r.changed() { self.poner_gpu(on); }
            if self.gpu_on && self.q == Calidad::Exacta { ui.weak("exacta: CPU"); }
            else if self.gpu_on { if let Some(a) = &self.gpu_prueba { ui.weak(a.as_str()); } }
            if let Some(a) = &self.gpu_aviso { ui.colored_label(egui::Color32::from_rgb(255, 170, 60), a.as_str()); }
            if ui.button("Reiniciar ediciones").clicked() { self.estado.ediciones.clear(); self.invalidar(); }
            ui.separator();
            ui.label(format!("render: {:.0} ms", self.ultimo_ms));
            ui.weak(format!("{} · ediciones solo en memoria (no se escribe al .xstage/.tvg)", self.frames[self.cur].nombre));
        });
    }

    /// Línea de tiempo al estilo de la referencia: transporte con iconos, Frame/Start/Stop, regla con números, filas con ojo + celdas por fotograma y cabezal rojo.
    /// Filas: «Escena» (una celda por fotograma horneado), la capa seleccionada (celda si la pieza existe; punto y nombre del dibujo cuando cambia) y piezas/cutters por fotograma.
    fn ui_timeline(&mut self, ui: &mut egui::Ui) {
        use egui::{pos2, vec2, Align2, Color32, FontId, Rect, Sense, Stroke};
        let n = self.frames.len();
        ui.horizontal(|ui| {
            if iconos::boton(ui, Icono::Inicio, false, true, 26.0, "Primer fotograma").clicked() { self.cur = 0; }
            if iconos::boton(ui, if self.playing { Icono::Pausa } else { Icono::Play }, self.playing, true, 26.0, "Reproducir / pausa").clicked() { self.playing = !self.playing; self.t_play = Instant::now(); }
            if iconos::boton(ui, Icono::Fin, false, true, 26.0, "Último fotograma").clicked() { self.cur = n - 1; }
            ui.separator();
            ui.label("Frame");
            ui.strong(self.frames[self.cur].fotograma.to_string());
            ui.label("Start");
            ui.strong(self.frames[0].fotograma.to_string());
            ui.label("Stop");
            ui.strong(self.frames[n - 1].fotograma.to_string());
            ui.add(egui::DragValue::new(&mut self.fps).range(1.0..=60.0).suffix(" fps"));
        });
        let (lw, rh, fh) = (190.0, 20.0, 24.0);
        let disp = ui.available_width();
        let cw = ((disp - lw) / n as f32).clamp(22.0, 96.0);
        let alto = rh + 3.0 * fh + 6.0;
        let sel_key = self.sel.clone();
        egui::ScrollArea::horizontal().auto_shrink([false, false]).show(ui, |ui| {
            let (rect, resp) = ui.allocate_exact_size(vec2((lw + cw * n as f32).max(disp), alto), Sense::click_and_drag());
            let x0 = rect.left() + lw;
            let mut alternar = None;
            if resp.dragged() || resp.clicked() {
                if let Some(pos) = resp.interact_pointer_pos() {
                    if pos.x >= x0 { self.cur = (((pos.x - x0) / cw).floor() as isize).clamp(0, n as isize - 1) as usize; }
                    else if resp.clicked() && pos.y > rect.top() + rh + fh && pos.y < rect.top() + rh + 2.0 * fh && pos.x < rect.left() + 28.0 { alternar = sel_key.clone(); }
                }
            }
            if let Some(k) = alternar { // clic en el ojo de la fila de la capa: prende/apaga la pieza seleccionada
                if !self.estado.ocultas.remove(&k) { self.estado.ocultas.insert(k); }
                self.invalidar();
            }
            let p = ui.painter_at(rect);
            p.rect_filled(rect, 0.0, Color32::from_gray(34));
            let gris = |v: u8| Color32::from_gray(v);
            // regla
            p.rect_filled(Rect::from_min_size(rect.min, vec2(rect.width(), rh)), 0.0, gris(48));
            for i in 0..n {
                let x = x0 + cw * i as f32;
                p.line_segment([pos2(x, rect.top() + rh - 5.0), pos2(x, rect.top() + rh)], Stroke::new(1.0, gris(110)));
                if i == self.cur {
                    p.rect_filled(Rect::from_min_size(pos2(x, rect.top()), vec2(cw, rh)), 0.0, Color32::from_rgb(200, 40, 50));
                }
                p.text(pos2(x + cw / 2.0, rect.top() + rh / 2.0), Align2::CENTER_CENTER, self.frames[i].fotograma.to_string(), FontId::proportional(11.0), if i == self.cur { Color32::WHITE } else { gris(175) });
            }
            let pieza = |i: usize| sel_key.as_ref().and_then(|k| self.frames[i].piezas.iter().find(|p| &p.key == k));
            let nombre_sel = sel_key.as_deref().and_then(|k| k.split('@').next()).and_then(|id| id.rsplit('/').next()).unwrap_or("(sin selección)").to_string();
            let oculta = sel_key.as_ref().map(|k| self.estado.ocultas.contains(k)).unwrap_or(false);
            let filas = [("Escena".to_string(), Icono::Ojo), (nombre_sel, if oculta { Icono::OjoCerrado } else { Icono::Ojo }), ("Piezas · cutters".to_string(), Icono::Ojo)];
            for (k, (titulo, ic)) in filas.iter().enumerate() {
                let y = rect.top() + rh + fh * k as f32;
                let fila = Rect::from_min_size(pos2(rect.left(), y), vec2(rect.width(), fh));
                p.rect_filled(fila, 0.0, if k % 2 == 0 { gris(38) } else { gris(42) });
                iconos::dibujar(&p, Rect::from_min_size(pos2(rect.left() + 5.0, y + 3.0), vec2(18.0, 18.0)), *ic, if k == 1 && sel_key.is_none() { gris(90) } else { gris(200) });
                p.with_clip_rect(Rect::from_min_size(pos2(rect.left() + 28.0, y), vec2(lw - 32.0, fh))).text(pos2(rect.left() + 30.0, y + fh / 2.0), Align2::LEFT_CENTER, titulo, FontId::proportional(13.0), gris(225));
                let mut prev: Option<String> = None;
                for i in 0..n {
                    let c = Rect::from_min_size(pos2(x0 + cw * i as f32, y), vec2(cw, fh)).shrink2(vec2(0.5, 1.5));
                    let pc = p.with_clip_rect(c);
                    match k {
                        0 => { pc.rect_filled(c, 2.0, Color32::from_rgb(38, 92, 128)); }
                        1 => match pieza(i) {
                            Some(pz) => {
                                pc.rect_filled(c, 2.0, if oculta { gris(52) } else { Color32::from_rgb(78, 78, 98) });
                                let d = pz.dibujo.rsplit('/').next().unwrap_or("").trim_end_matches(".svg").to_string();
                                if prev.as_deref() != Some(d.as_str()) {
                                    pc.circle_filled(c.left_center() + vec2(7.0, 0.0), 3.0, gris(235));
                                    pc.text(c.left_center() + vec2(14.0, 0.0), Align2::LEFT_CENTER, &d, FontId::proportional(10.0), gris(225));
                                }
                                prev = Some(d);
                            }
                            None => { prev = None; }
                        },
                        _ => {
                            let f = &self.frames[i];
                            pc.rect_filled(c, 2.0, gris(52));
                            pc.text(c.center(), Align2::CENTER_CENTER, format!("{} · {}", f.piezas.len(), f.piezas.iter().filter(|p| !p.recorte.is_empty()).count()), FontId::proportional(10.0), gris(185));
                        }
                    }
                }
            }
            // cabezal rojo
            let xc = x0 + cw * (self.cur as f32 + 0.5);
            p.line_segment([pos2(xc, rect.top() + rh), pos2(xc, rect.bottom())], Stroke::new(1.5, Color32::from_rgb(220, 50, 60)));
            p.rect_stroke(Rect::from_min_max(pos2(x0 + cw * self.cur as f32, rect.top() + rh), pos2(x0 + cw * (self.cur + 1) as f32, rect.bottom())), 0.0, Stroke::new(1.0, Color32::from_rgb(220, 50, 60)), egui::StrokeKind::Inside);
        });
    }

    fn ui_capas(&mut self, ui: &mut egui::Ui) {
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
        ui.weak("de adelante (arriba) hacia atrás");
        let f = self.filtro.to_lowercase();
        let idxs: Vec<usize> = (0..self.frames[self.cur].piezas.len()).rev().filter(|&i| f.is_empty() || self.frames[self.cur].piezas[i].key.to_lowercase().contains(&f)).collect();
        let mut cambio = false;
        let mut nueva_sel = None;
        egui::ScrollArea::vertical().auto_shrink([false, false]).show_rows(ui, 20.0, idxs.len(), |ui, rango| {
            for k in rango {
                let i = idxs[k];
                let p = &self.frames[self.cur].piezas[i];
                ui.horizontal(|ui| {
                    let vis = !self.estado.ocultas.contains(&p.key);
                    if iconos::boton(ui, if vis { Icono::Ojo } else { Icono::OjoCerrado }, false, true, 18.0, if vis { "Visible: clic para ocultar" } else { "Oculta: clic para mostrar" }).clicked() {
                        if vis { self.estado.ocultas.insert(p.key.clone()); } else { self.estado.ocultas.remove(&p.key); }
                        cambio = true;
                    }
                    let (nombre, grupo) = p.id.rsplit_once('/').map(|(g, n)| (n, g)).unwrap_or((p.id.as_str(), ""));
                    let editada = self.estado.ediciones.contains_key(&p.key);
                    let txt = format!("{:>3} {}{}{}", p.orden, nombre, if editada { " *" } else { "" }, if p.recorte.is_empty() { "" } else { " ✂" });
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
    }

    fn ui_params(&mut self, ui: &mut egui::Ui) {
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
    }

    fn ui_player(&mut self, ui: &mut egui::Ui) {
        let ctx = ui.ctx().clone();
        let tex = self.textura(&ctx);
        let tam = self.frames[self.cur].tam;
        let avail = ui.available_rect_before_wrap();
        let esc = (avail.width() / tam.0 as f32).min(avail.height() / tam.1 as f32);
        let r = egui::Rect::from_center_size(avail.center(), egui::vec2(tam.0 as f32 * esc, tam.1 as f32 * esc));
        // herramientas sobre el cuadro: clic selecciona; mover/rotar/escalar editan la pieza seleccionada arrastrando (solo en memoria)
        let resp = ui.interact(r, egui::Id::new("player_cuadro"), egui::Sense::click_and_drag());
        match self.herr {
            Herr::Seleccionar => {
                if resp.clicked() {
                    if let Some(pos) = resp.interact_pointer_pos() {
                        self.sel = self.recoger(((pos.x - r.left()) / r.width(), (pos.y - r.top()) / r.height()));
                        self.sincronizar_nodos();
                    }
                }
            }
            h => {
                if resp.dragged() {
                    if let Some(k) = self.sel.clone() {
                        let d = resp.drag_delta();
                        let cam = self.frames[self.cur].cam;
                        let mut ed = self.estado.ediciones.get(&k).copied().unwrap_or_default();
                        match h {
                            Herr::Mover => { ed.dx += d.x / esc / cam.2 as f32; ed.dy -= d.y / esc / cam.3 as f32; }
                            Herr::Rotar => ed.rot -= d.x * 0.5,
                            _ => { let f = 1.0 + d.x * 0.004; ed.esc *= f; ed.escy *= f; }
                        }
                        self.estado.ediciones.insert(k, ed);
                        self.invalidar();
                    }
                }
            }
        }
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
    }

    fn ui_nodos(&mut self, ui: &mut egui::Ui) {
        let mut pulsado = None;
        match &self.grafo {
            Some(g) => pulsado = nodos::mostrar(ui, g, &mut self.vista),
            None => { ui.label("Sin grafo: genera <datos de trabajo omitidos> con scripts\\grafo_visor.py"); }
        }
        if let Some(id) = pulsado {
            if let Some(p) = self.frames[self.cur].piezas.iter().rev().find(|p| p.id == id) { self.sel = Some(p.key.clone()); }
        }
    }
}

struct Cuerpo<'a>(&'a mut Visor);
impl DockContent<Panel> for Cuerpo<'_> {
    fn body(&mut self, ui: &mut egui::Ui, panel: &Panel) {
        match panel {
            Panel::Capas => self.0.ui_capas(ui),
            Panel::Player => self.0.ui_player(ui),
            Panel::Nodos => self.0.ui_nodos(ui),
            Panel::Timeline => self.0.ui_timeline(ui),
            Panel::Parametros => self.0.ui_params(ui),
        }
    }
    fn logical_label(&self, panel: &Panel) -> String { panel.nombre().to_string() }
}

struct App {
    visor: Visor,
    layout: Layout<Panel>,
    shot: Option<PathBuf>,
    frames: u32,
    pedida: bool,
    auto: Option<(String, u32, u32)>,
    auto_analizar: Option<(String, bool, Option<String>, bool)>, // (carpeta, lanzar, carpeta del log, log para compartir)
    lanzar_analisis: bool, // --analizar-correr: lanza el análisis en cuanto termina de listar los planos
    quieto: u32, // cuadros sin horneado en curso (la captura espera a que termine)
}

impl eframe::App for App {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        let ctx = ui.ctx().clone();
        self.frames += 1;
        let v = &mut self.visor;
        if let Some((x, a, b)) = self.auto.take() {
            v.dlg.xstage = x; v.dlg.desde = a; v.dlg.hasta = b; v.dlg.abierto = true;
            v.dlg.lanzar(&ctx);
        }
        if let Some((carpeta, lanzar, log, comp)) = self.auto_analizar.take() {
            v.ana.carpeta = carpeta; v.ana.abierto = true; v.ana.compartible = comp;
            if let Some(l) = log { v.ana.log_dir = l; }
            v.ana.escanear(&ctx);
            self.lanzar_analisis = lanzar;
        }
        if self.lanzar_analisis && v.ana.planos_listos() { self.lanzar_analisis = false; v.ana.lanzar(&ctx); }
        if !v.dlg.corriendo() && !v.ana.ocupado() && !self.lanzar_analisis { self.quieto += 1; }
        if v.dlg.corriendo() { ctx.request_repaint_after(std::time::Duration::from_millis(250)); }
        if v.playing && v.t_play.elapsed().as_secs_f32() >= 1.0 / v.fps {
            v.t_play = Instant::now();
            v.cur = (v.cur + 1) % v.frames.len();
        }
        if v.playing || self.shot.is_some() { ctx.request_repaint(); }
        if ctx.input(|i| i.modifiers.command && i.key_pressed(egui::Key::Z)) { v.deshacer(); }
        if ctx.input(|i| i.modifiers.command && i.key_pressed(egui::Key::Y)) { v.rehacer_(); }
        // menu principal (como el de Harmony); «Ventanas» abre/cierra paneles con las acciones Open/Close del docking de craft-ui
        egui::Panel::top("menu").show(ui, |ui| {
            egui::MenuBar::new().ui(ui, |ui| {
                ui.menu_button("Archivo", |ui| {
                    if ui.button("Abrir…").on_hover_text("Elige un .xstage y una carpeta de salida; convierte todos los fotogramas y los abre.").clicked() {
                        ui.close();
                        let c = ui.ctx().clone();
                        if !v.dlg.corriendo() { v.dlg.abrir_rapido(&c); }
                    }
                    if ui.button("Abrir escena (opciones)…").clicked() { v.dlg.abierto = true; ui.close(); }
                    if ui.button("Abrir carpeta horneada…").clicked() { v.dlg.abierto = true; ui.close(); }
                    ui.separator();
                    if ui.button("Analizar carpeta de planos…").on_hover_text("Lista los .xstage de una carpeta y detecta lo que pegcraft no conoce o no soporta; deja un log.").clicked() {
                        ui.close();
                        v.ana.abierto = true;
                        if v.ana.carpeta.trim().is_empty() { let c = ui.ctx().clone(); v.ana.elegir_carpeta(&c); }
                    }
                    ui.separator();
                    if ui.button("Salir").clicked() { ctx.send_viewport_cmd(egui::ViewportCommand::Close); }
                });
                ui.menu_button("Editar", |ui| {
                    if ui.add_enabled(!v.hist.is_empty(), egui::Button::new("Deshacer  Ctrl+Z")).clicked() { v.deshacer(); ui.close(); }
                    if ui.add_enabled(!v.rehacer.is_empty(), egui::Button::new("Rehacer  Ctrl+Y")).clicked() { v.rehacer_(); ui.close(); }
                    ui.separator();
                    if ui.button("Reiniciar ediciones").clicked() { v.estado.ediciones.clear(); v.invalidar(); ui.close(); }
                    if ui.button("Mostrar todas las capas").clicked() { v.estado.ocultas.clear(); v.invalidar(); ui.close(); }
                });
                ui.menu_button("Ver", |ui| {
                    ui.label("Calidad del render");
                    for (q, n) in [(Calidad::Rapida, "½ rápida"), (Calidad::Completa, "1× completa"), (Calidad::Exacta, "1× exacta (ss2 + gauss)")] {
                        if ui.radio_value(&mut v.q, q, n).changed() { v.invalidar(); }
                    }
                    ui.separator();
                    let mut on = v.gpu_on;
                    if ui.checkbox(&mut on, "Acelerar por GPU").changed() { v.poner_gpu(on); }
                    ui.separator();
                    if ui.button("Restablecer espacio de trabajo").clicked() { self.layout = espacio(v.espacio); ui.close(); }
                });
                ui.menu_button("Play", |ui| {
                    if ui.button(if v.playing { "Pausa" } else { "Reproducir" }).clicked() { v.playing = !v.playing; v.t_play = Instant::now(); ui.close(); }
                    if ui.button("Primer fotograma").clicked() { v.cur = 0; ui.close(); }
                    if ui.button("Último fotograma").clicked() { v.cur = v.frames.len() - 1; ui.close(); }
                });
                ui.menu_button("Ventanas", |ui| {
                    for p in PANELES {
                        let mut abierto = self.layout.contains(&p);
                        if ui.checkbox(&mut abierto, p.nombre()).changed() {
                            let a = if abierto { Action::Open { panel: p, anchor: None } } else { Action::Close { panel: p } };
                            if let Err(e) = self.layout.apply(a) { eprintln!("ventanas: {e:?}"); }
                        }
                    }
                });
                ui.menu_button("Ayuda", |ui| {
                    ui.label("pegcraft-viewer-craft (spike) — ver <datos de trabajo omitidos>");
                    ui.label("Las ediciones viven en memoria: no se escribe al .xstage ni a los .tvg.");
                });
            });
        });
        analizar::mostrar(&ctx, &mut v.ana);
        match abrir::mostrar(&ctx, &mut v.dlg) {
            abrir::Orden::Cargar(r, g) => match v.cargar_carpeta(&r, g) {
                Ok(()) => v.dlg.abierto = false,
                Err(e) => { v.dlg.trabajo.lock().unwrap().fase = abrir::Fase::Error(e); v.dlg.abierto = true; }
            },
            abrir::Orden::Nada => {}
        }
        egui::Panel::top("barra_herramientas").show(ui, |ui| {
            ui.horizontal(|ui| {
                ui.label("Espacio de trabajo");
                egui::ComboBox::from_id_salt("espacio").selected_text(ESPACIOS[v.espacio]).show_ui(ui, |ui| {
                    for (i, n) in ESPACIOS.iter().enumerate() {
                        if ui.selectable_value(&mut v.espacio, i, *n).clicked() { self.layout = espacio(i); }
                    }
                });
                ui.separator();
                v.ui_barra(ui);
            });
        });
        egui::Panel::left("herramientas").exact_size(46.0).show(ui, |ui| {
            ui.add_space(4.0);
            for (h, ic, t) in [(Herr::Seleccionar, Icono::Seleccionar, "Seleccionar: clic en el cuadro"), (Herr::Mover, Icono::Mover, "Mover: arrastra la pieza seleccionada"), (Herr::Rotar, Icono::Rotar, "Rotar: arrastra en horizontal"), (Herr::Escalar, Icono::Escalar, "Escalar: arrastra en horizontal")] {
                if iconos::boton(ui, ic, v.herr == h, true, 34.0, t).clicked() { v.herr = h; }
                ui.add_space(2.0);
            }
        });
        egui::Panel::bottom("estado").show(ui, |ui| {
            ui.horizontal(|ui| {
                let sel = v.sel.as_deref().and_then(|k| k.rsplit('/').next()).unwrap_or("—");
                ui.label(format!("fotograma {} · herramienta {:?} · selección {} · {} editadas · {} ocultas · render {:.0} ms ({})", v.frames[v.cur].fotograma, v.herr, sel, v.estado.ediciones.len(), v.estado.ocultas.len(), v.ultimo_ms,
                    if v.gpu_on && v.q != Calidad::Exacta && v.gpu.is_some() { "GPU" } else { "CPU" }));
            });
        });
        let style = DockStyle::from_ui(ui);
        let out = DockArea::new(egui::Id::new("dock")).show_content(ui, &self.layout, &style, &mut Cuerpo(v));
        if !out.actions.is_empty() {
            if let Err(e) = self.layout.apply_all(out.actions, |_| Default::default()) { eprintln!("dock: {e:?}"); }
        }
        self.visor.registrar();
        // captura (modo --screenshot): pide la imagen a eframe tras ~60 cuadros, la guarda y cierra
        if let Some(ruta) = self.shot.clone() {
            if self.quieto >= 60 && self.frames > 60 && !self.pedida {
                self.pedida = true;
                let (ctx2, ms) = (ctx.clone(), self.visor.ultimo_ms);
                ctx.request_screenshot(move |img| {
                    let [w, h] = img.size;
                    let mut pm = tiny_skia::Pixmap::new(w as u32, h as u32).unwrap();
                    for (d, c) in pm.data_mut().chunks_exact_mut(4).zip(img.pixels.iter()) {
                        d[0] = c.r(); d[1] = c.g(); d[2] = c.b(); d[3] = 255;
                    }
                    if let Some(p) = ruta.parent() { let _ = std::fs::create_dir_all(p); }
                    pm.save_png(&ruta).expect("png");
                    eprintln!("captura -> {:?} ({}x{}), render {:.0} ms", ruta, w, h, ms);
                    ctx2.send_viewport_cmd(egui::ViewportCommand::Close);
                });
            }
        }
    }
}

fn medir(o: &Opciones) {
    let mut v = Visor::nuevo(o).expect("cargar");
    // PEGCRAFT_MEDIR_CADA=K mide uno de cada K fotogramas (Completa y Exacta tardan segundos por fotograma)
    let cada: usize = std::env::var("PEGCRAFT_MEDIR_CADA").ok().and_then(|s| s.parse().ok()).filter(|k| *k >= 1).unwrap_or(1);
    let todos = std::mem::take(&mut v.frames);
    v.frames = todos.into_iter().step_by(cada).collect();
    let n = v.frames.len();
    println!("{} fotogramas medidos (1 de cada {}), {} piezas en el primero", n, cada, v.frames[0].piezas.len());
    // Reproducción real: 1.ª pasada con la caché de dibujos vacía (carga y teselado de SVG + rasterizado), 2.ª con la caché llena (solo rasterizado);
    // la diferencia es la carga de SVG. «ColorImage» = construir la imagen que egui sube a la GPU (copia); la subida a la GPU no se mide aquí.
    // Con --gpu se miden Rápida y Completa por GPU (vello; Exacta es siempre CPU); el tiempo incluye la lectura de vuelta a la CPU.
    let mut gpu = if o.gpu {
        match render_gpu::Gpu::nuevo() { Ok(g) => { println!("GPU: {} (init {:.0} ms)", g.adaptador, g.init_ms); Some(g) } Err(e) => { println!("GPU no disponible: {e}"); return; } }
    } else { None };
    let calidades: &[Calidad] = if gpu.is_some() { &[Calidad::Rapida, Calidad::Completa] } else { &[Calidad::Rapida, Calidad::Completa, Calidad::Exacta] };
    for &q in calidades {
        v.cache = render::Cache::default();
        if let Some(g) = gpu.as_mut() { g.vaciar_cache(); }
        let paso = |v: &mut Visor, gpu: &mut Option<render_gpu::Gpu>| -> (Option<tiny_skia::Pixmap>, f32) {
            let t = Instant::now();
            let mut ult = None;
            for f in &v.frames {
                ult = Some(match gpu.as_mut() {
                    Some(g) => g.render(f, &v.estado, q, true).expect("render GPU"),
                    None => render::render(f, &mut v.cache, &v.estado, q),
                });
            }
            (ult, t.elapsed().as_secs_f32() * 1000.0 / n as f32)
        };
        let (_, fria) = paso(&mut v, &mut gpu);
        let (ult, tibia) = paso(&mut v, &mut gpu);
        let pm = ult.unwrap();
        let t = Instant::now();
        for _ in 0..20 { let _ = egui::ColorImage::from_rgba_premultiplied([pm.width() as usize, pm.height() as usize], pm.data()); }
        let subida = t.elapsed().as_secs_f32() * 1000.0 / 20.0;
        println!("{:?}{}: 1.a pasada {:.1} ms/fot ({:.1} fps) | caché llena {:.1} ms/fot ({:.1} fps) | carga SVG {:.1} ms/fot | ColorImage {:.1} ms | {} SVG en caché",
                 q, if gpu.is_some() { " [GPU]" } else { " [CPU]" }, fria, 1000.0 / fria, tibia, 1000.0 / tibia, fria - tibia, subida,
                 gpu.as_ref().map(|g| g.n_dibujos()).unwrap_or(v.cache.dibujos.len()));
    }
}

/// Windows: engancha stdout/stderr a la consola del proceso padre (si la hay) para que las salidas de consola sigan viéndose con windows_subsystem = "windows".
#[cfg(windows)]
fn adjuntar_consola() {
    use std::os::windows::io::IntoRawHandle;
    unsafe extern "system" {
        fn AttachConsole(pid: u32) -> i32;
        fn GetStdHandle(n: u32) -> isize;
        fn SetStdHandle(n: u32, h: isize) -> i32;
    }
    const ATTACH_PARENT_PROCESS: u32 = 0xFFFF_FFFF;
    const STD_OUTPUT_HANDLE: u32 = -11i32 as u32;
    const STD_ERROR_HANDLE: u32 = -12i32 as u32;
    unsafe {
        if AttachConsole(ATTACH_PARENT_PROCESS) == 0 { return; } // sin consola padre (doble clic, Start-Process): nada que enganchar
        // un exe de ventana arranca con los manejadores estándar vacíos; si el padre no los redirigió, apuntarlos a la consola
        for n in [STD_OUTPUT_HANDLE, STD_ERROR_HANDLE] {
            let h = GetStdHandle(n);
            if h == 0 || h == -1 {
                if let Ok(f) = std::fs::OpenOptions::new().write(true).open("CONOUT$") { SetStdHandle(n, f.into_raw_handle() as isize); }
            }
        }
    }
}
#[cfg(not(windows))]
fn adjuntar_consola() {}

fn main() -> eframe::Result {
    adjuntar_consola();
    let o = args();
    if o.medir { medir(&o); return Ok(()); }
    if let Some((salida, cuadros)) = &o.comparar { comparar_gpu::comparar(&o.ruta, salida, cuadros); return Ok(()); }
    let mut visor = match Visor::nuevo(&o) { Ok(v) => v, Err(e) => { eprintln!("error: {e}"); std::process::exit(1) } };
    if let Some(g) = &o.grupo { visor.vista.grupo = g.clone(); visor.vista.sel = None; visor.vista.ajustar = true; }
    let options = eframe::NativeOptions { viewport: egui::ViewportBuilder::default().with_inner_size([o.tam.0, o.tam.1]).with_title("pegcraft-viewer-craft"), ..Default::default() };
    let layout = espacio(if o.nodos_grande { 1 } else { 0 });
    let shot = o.shot.clone();
    let o_abrir = o.abrir.clone();
    let o_analizar = o.analizar.clone().map(|c| (c, o.analizar_correr, o.log_analisis.clone(), o.analizar_compartible));
    eframe::run_native("pegcraft-viewer-craft", options, Box::new(move |cc| {
        // pila de fuentes de craft-ui (la misma de todos los Craft): caras por omision de egui + fuentes del sistema para simbolos (⏮ ▶ ✂)
        use egui::FontFamily::{Monospace, Proportional};
        craft_ui::fonts::UiFonts::new(&craft_ui::fonts::I18nScripts)
            .egui_face("Ubuntu-Light", &[Proportional])
            .egui_face("Hack", &[Monospace])
            .system_fonts(craft_ui::fonts::SystemFonts::AfterCraft)
            .install(&cc.egui_ctx);
        cc.egui_ctx.set_theme(egui::Theme::Dark);
        Ok(Box::new(App { visor, layout, shot, frames: 0, pedida: false, auto: o_abrir, auto_analizar: o_analizar, lanzar_analisis: false, quieto: 0 }))
    }))
}
