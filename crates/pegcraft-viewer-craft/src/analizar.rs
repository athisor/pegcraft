// Archivo > Analizar carpeta de planos…: lista los .xstage de una carpeta (recursivo), deja elegir cuáles y llama a `python -m pegcraft analizar` en segundo
// plano. El análisis detecta lo que pegcraft NO conoce o no soporta (tipos de nodo, atributos, columnas, deformadores, efectos, rasgos de .tvg/.plt...) y
// escribe un log (`<base>.jsonl`, `<base>.md`, `<base>.resumen.json`). SOLO LECTURA sobre los planos (pueden estar en carpetas de producción); el log nunca
// va a las carpetas protegidas (`abrir::permitida`).
use crate::abrir::{absoluta, comando_py, entorno, permitida, sin_ventana, Fase};
use std::{
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::{atomic::{AtomicBool, Ordering}, Arc, Mutex},
    time::Duration,
};

/// Carpeta del log por omisión: `PEGCRAFT_LOG_ANALISIS` si está definida; si no, `trabajo\analisis` bajo el repositorio.
fn log_por_omision() -> String {
    std::env::var("PEGCRAFT_LOG_ANALISIS").ok().filter(|s| !s.trim().is_empty()).unwrap_or_else(|| entorno().trabajo.join("analisis").to_string_lossy().into_owned())
}
const TOPE_PLANOS: usize = 20000;

#[derive(Clone, Default)]
pub struct Resumen {
    pub escenas: u64,
    pub con_hallazgos: u64,
    pub con_error: u64,
    pub distintos: u64,
    pub t_medio: f64,
    pub t_max: f64,
    pub terminado: bool,
    pub por_categoria: Vec<(String, u64, u64, u64)>, // (categoría, claves, escenas, n)
    pub top: Vec<(String, String, u64, u64)>,        // (categoría, clave, escenas, n)
}

pub struct Trabajo {
    pub fase: Fase,
    pub hecho: usize,
    pub total: usize,
    pub actual: String,
    pub base: PathBuf,
    pub resumen: Option<Resumen>,
}

#[derive(Default)]
struct Escaneo {
    lista: Vec<PathBuf>,
    listo: bool,
    activo: bool,
}

pub struct Analisis {
    pub abierto: bool,
    pub carpeta: String,
    pub filtro: String,
    pub planos: Vec<(PathBuf, bool)>,
    pub log_dir: String,
    pub fotogramas: String,
    pub compartible: bool, // «Log para compartir»: escribe además <base>_compartible.json (sin rutas ni nombres) y lo verifica
    escaneo: Arc<Mutex<Escaneo>>,
    pub trabajo: Arc<Mutex<Trabajo>>,
    pub cancelar: Arc<AtomicBool>,
}

impl Default for Analisis {
    fn default() -> Self {
        let log_dir = log_por_omision();
        Analisis {
            abierto: false, carpeta: String::new(), filtro: String::new(), planos: vec![], log_dir, fotogramas: "muestra".into(), compartible: false,
            escaneo: Arc::new(Mutex::new(Escaneo::default())),
            trabajo: Arc::new(Mutex::new(Trabajo { fase: Fase::Libre, hecho: 0, total: 0, actual: String::new(), base: PathBuf::new(), resumen: None })),
            cancelar: Arc::new(AtomicBool::new(false)),
        }
    }
}

/// `AAAAMMDD_HHMM` de la hora local (Windows: GetLocalTime; en otros sistemas, UTC).
fn marca_hora() -> String {
    #[cfg(windows)]
    {
        #[repr(C)]
        #[derive(Default)]
        struct SystemTime { anio: u16, mes: u16, dia_semana: u16, dia: u16, hora: u16, minuto: u16, segundo: u16, ms: u16 }
        unsafe extern "system" { fn GetLocalTime(t: *mut SystemTime); }
        let mut t = SystemTime::default();
        unsafe { GetLocalTime(&mut t) };
        return format!("{:04}{:02}{:02}_{:02}{:02}", t.anio, t.mes, t.dia, t.hora, t.minuto);
    }
    #[allow(unreachable_code)]
    {
        let s = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
        format!("utc_{s}")
    }
}

/// Lee `<base>.resumen.json` (lo reescribe el análisis tras cada escena).
fn leer_resumen(base: &Path) -> Option<Resumen> {
    let txt = std::fs::read_to_string(base.with_extension("resumen.json")).ok()?;
    let j: serde_json::Value = serde_json::from_str(&txt).ok()?;
    let u = |v: &serde_json::Value, k: &str| v.get(k).and_then(|x| x.as_u64()).unwrap_or(0);
    let f = |v: &serde_json::Value, k: &str| v.get(k).and_then(|x| x.as_f64()).unwrap_or(0.0);
    let s = |v: &serde_json::Value, k: &str| v.get(k).and_then(|x| x.as_str()).unwrap_or("").to_string();
    let mut r = Resumen {
        escenas: u(&j, "escenas"), con_hallazgos: u(&j, "escenas_con_hallazgos"), con_error: u(&j, "escenas_con_error"), distintos: u(&j, "hallazgos_distintos"),
        t_medio: f(&j, "t_medio_s"), t_max: f(&j, "t_max_s"), terminado: j.get("terminado").and_then(|x| x.as_bool()).unwrap_or(false), ..Default::default()
    };
    if let Some(o) = j.get("por_categoria").and_then(|x| x.as_object()) {
        for (k, v) in o { r.por_categoria.push((k.clone(), u(v, "claves"), u(v, "escenas"), u(v, "n"))); }
    }
    if let Some(a) = j.get("top").and_then(|x| x.as_array()) {
        for v in a.iter().take(40) { r.top.push((s(v, "categoria"), s(v, "clave"), u(v, "escenas"), u(v, "n"))); }
    }
    Some(r)
}

fn abrir_con_el_sistema(ruta: &Path, seleccionar: bool) {
    let mut c = if seleccionar {
        let mut c = Command::new("explorer.exe");
        c.arg(format!("/select,{}", ruta.display()));
        c
    } else {
        let mut c = Command::new("cmd");
        c.args(["/C", "start", ""]).arg(ruta);
        c
    };
    sin_ventana(&mut c);
    let _ = c.spawn();
}

impl Analisis {
    pub fn ocupado(&self) -> bool {
        self.trabajo.lock().unwrap().fase == Fase::Corriendo || self.escaneo.lock().unwrap().activo
    }
    pub fn corriendo(&self) -> bool { self.trabajo.lock().unwrap().fase == Fase::Corriendo }
    /// true cuando ya terminó de listar y hay planos (para lanzar el análisis desde la línea de comandos).
    pub fn planos_listos(&mut self) -> bool { self.absorber_escaneo(); !self.planos.is_empty() && !self.escaneo.lock().unwrap().activo }

    /// Elige la carpeta de planos (selector nativo) y la escanea.
    pub fn elegir_carpeta(&mut self, ctx: &egui::Context) {
        if let Some(p) = rfd::FileDialog::new().set_title("Carpeta de planos a analizar").pick_folder() {
            self.carpeta = p.to_string_lossy().into();
            self.escanear(ctx);
        }
    }

    /// Lista los .xstage de `self.carpeta` (recursivo) en un hilo; el resultado entra a `planos` desde la ventana.
    pub fn escanear(&mut self, ctx: &egui::Context) {
        let raiz = PathBuf::from(self.carpeta.trim());
        self.planos.clear();
        *self.escaneo.lock().unwrap() = Escaneo { lista: vec![], listo: false, activo: true };
        let (e, ctx) = (self.escaneo.clone(), ctx.clone());
        std::thread::spawn(move || {
            let mut lista: Vec<PathBuf> = vec![];
            let mut pila = vec![raiz];
            while let Some(d) = pila.pop() {
                let Ok(rd) = std::fs::read_dir(&d) else { continue };
                for ent in rd.flatten() {
                    let p = ent.path();
                    let Ok(tipo) = ent.file_type() else { continue };
                    if tipo.is_dir() { pila.push(p); }
                    else if tipo.is_file() && p.extension().is_some_and(|x| x.eq_ignore_ascii_case("xstage")) { lista.push(p); }
                }
                if lista.len() >= TOPE_PLANOS { break; }
            }
            lista.sort();
            *e.lock().unwrap() = Escaneo { lista, listo: true, activo: false };
            ctx.request_repaint();
        });
    }

    fn absorber_escaneo(&mut self) {
        let mut e = self.escaneo.lock().unwrap();
        if e.listo {
            self.planos = std::mem::take(&mut e.lista).into_iter().map(|p| (p, true)).collect();
            e.listo = false;
        }
    }

    pub fn lanzar(&mut self, ctx: &egui::Context) {
        let elegidos: Vec<&PathBuf> = self.planos.iter().filter(|(_, s)| *s).map(|(p, _)| p).collect();
        if elegidos.is_empty() { self.fallo("no hay planos elegidos".into()); return; }
        let dir = if entorno().paquete { PathBuf::from(absoluta(self.log_dir.trim())) } else { PathBuf::from(self.log_dir.trim()) };
        if !permitida(&dir) { self.fallo(format!("carpeta del log no permitida (protegida o con ..): {}", dir.display())); return; }
        if let Err(e) = std::fs::create_dir_all(&dir) { self.fallo(format!("no se pudo crear {}: {e}", dir.display())); return; }
        let base = dir.join(format!("analisis_{}", marca_hora()));
        let lista = base.with_extension("planos.txt");
        let texto: String = elegidos.iter().map(|p| format!("{}\n", p.display())).collect();
        if let Err(e) = std::fs::write(&lista, texto) { self.fallo(format!("no se pudo escribir {}: {e}", lista.display())); return; }
        let total = elegidos.len();
        *self.trabajo.lock().unwrap() = Trabajo { fase: Fase::Corriendo, hecho: 0, total, actual: "abriendo…".into(), base: base.clone(), resumen: None };
        self.cancelar.store(false, Ordering::Relaxed);
        let fot = if self.fotogramas.trim().is_empty() { "muestra".to_string() } else { self.fotogramas.trim().to_string() };
        let mut args: Vec<String> = vec!["-m".into(), "pegcraft".into(), "analizar".into(), absoluta(self.carpeta.trim()), "--planos".into(), lista.to_string_lossy().into(),
                                          "--log".into(), base.to_string_lossy().into(), "--fotogramas".into(), fot];
        if self.compartible { args.push("--compartible".into()); }
        let (t, cancelar, ctx) = (self.trabajo.clone(), self.cancelar.clone(), ctx.clone());
        std::thread::spawn(move || {
            let r = correr(&args, &base.with_extension("stderr.log"), &cancelar, &t, &ctx);
            let resumen = leer_resumen(&base);
            let mut g = t.lock().unwrap();
            g.resumen = resumen;
            g.fase = match r { Ok(()) => Fase::Listo, Err(e) if e == "cancelado" => Fase::Error("cancelado (el log queda con lo analizado hasta aquí)".into()), Err(e) => Fase::Error(e) };
            drop(g);
            ctx.request_repaint();
        });
    }
    fn fallo(&mut self, m: String) { self.trabajo.lock().unwrap().fase = Fase::Error(m); }
}

/// Lanza `python -m pegcraft analizar …` y lee el avance de stdout (`escena i/N ruta`, `hecho i/N …`); stderr va a un archivo. Cancelable matando el proceso.
fn correr(args: &[String], log: &Path, cancelar: &AtomicBool, t: &Arc<Mutex<Trabajo>>, ctx: &egui::Context) -> Result<(), String> {
    use std::io::{BufRead, BufReader};
    let f = std::fs::File::create(log).map_err(|e| e.to_string())?;
    let mut c = comando_py(args);
    c.stdout(Stdio::piped()).stderr(Stdio::from(f));
    sin_ventana(&mut c);
    let mut h = c.spawn().map_err(|e| format!("no se pudo lanzar {}: {e}", entorno().py))?;
    let out = h.stdout.take().ok_or("sin stdout")?;
    let (t2, ctx2) = (t.clone(), ctx.clone());
    let lector = std::thread::spawn(move || {
        for l in BufReader::new(out).lines().map_while(Result::ok) {
            let l = l.trim();
            let (clave, resto) = l.split_once(' ').unwrap_or((l, ""));
            if clave != "escena" && clave != "hecho" { continue; }
            let (par, nombre) = resto.split_once(' ').unwrap_or((resto, ""));
            let Some((i, n)) = par.split_once('/') else { continue };
            let (Ok(i), Ok(n)) = (i.parse::<usize>(), n.parse::<usize>()) else { continue };
            let mut g = t2.lock().unwrap();
            g.total = n;
            if clave == "escena" {
                g.hecho = i.saturating_sub(1);
                g.actual = Path::new(nombre).file_name().map(|s| s.to_string_lossy().to_string()).unwrap_or_default();
            } else {
                g.hecho = i;
            }
            drop(g);
            ctx2.request_repaint();
        }
    });
    let r = loop {
        if cancelar.load(Ordering::Relaxed) {
            let _ = h.kill();
            let _ = h.wait();
            break Err("cancelado".to_string());
        }
        match h.try_wait() {
            Ok(Some(st)) if st.success() => break Ok(()),
            Ok(Some(st)) => {
                let cola = std::fs::read_to_string(log).unwrap_or_default().lines().rev().take(4).collect::<Vec<_>>().into_iter().rev().collect::<Vec<_>>().join(" | ");
                break Err(format!("salió con {st}: {cola}"));
            }
            Ok(None) => std::thread::sleep(Duration::from_millis(100)),
            Err(e) => break Err(e.to_string()),
        }
    };
    let _ = lector.join();
    r
}

/// Ventana «Analizar carpeta de planos».
pub fn mostrar(ctx: &egui::Context, a: &mut Analisis) {
    a.absorber_escaneo();
    if !a.abierto { return; }
    let mut abierto = true;
    egui::Window::new("Analizar carpeta de planos").open(&mut abierto).default_width(720.0).show(ctx, |ui| {
        ui.strong("Qué no conoce pegcraft en estos planos");
        ui.weak("Solo lee los planos y sus .tvg/.plt (pueden estar en carpetas de producción). Mide una muestra de fotogramas (primero, medio y último) sin convertir SVG: ≈1–30 s por plano.");
        let corriendo = a.corriendo();
        ui.horizontal(|ui| {
            ui.label("carpeta");
            ui.add_enabled(!corriendo, egui::TextEdit::singleline(&mut a.carpeta).desired_width(480.0).hint_text(r"carpeta con planos (se buscan .xstage en todas sus subcarpetas)"));
            if ui.add_enabled(!corriendo, egui::Button::new("Examinar…")).clicked() { a.elegir_carpeta(ctx); }
            if ui.add_enabled(!corriendo && !a.carpeta.trim().is_empty(), egui::Button::new("Buscar")).on_hover_text("Vuelve a listar los .xstage de la carpeta").clicked() { a.escanear(ctx); }
        });
        let escaneando = a.escaneo.lock().unwrap().activo;
        if escaneando { ui.horizontal(|ui| { ui.spinner(); ui.label("buscando .xstage…"); }); ctx.request_repaint_after(Duration::from_millis(200)); }
        let f = a.filtro.to_lowercase();
        let visibles: Vec<usize> = (0..a.planos.len()).filter(|&i| f.is_empty() || a.planos[i].0.to_string_lossy().to_lowercase().contains(&f)).collect();
        let sel = a.planos.iter().filter(|(_, s)| *s).count();
        ui.horizontal(|ui| {
            ui.label(format!("{} plano(s) encontrados · {sel} elegidos", a.planos.len()));
            ui.add_enabled_ui(!corriendo, |ui| {
                if ui.button("Todos").on_hover_text("marca los que se ven con el filtro actual").clicked() { for &i in &visibles { a.planos[i].1 = true; } }
                if ui.button("Ninguno").on_hover_text("desmarca los que se ven con el filtro actual").clicked() { for &i in &visibles { a.planos[i].1 = false; } }
                ui.label("filtro");
                ui.add(egui::TextEdit::singleline(&mut a.filtro).desired_width(160.0).hint_text("trozo de ruta"));
            });
        });
        let base = PathBuf::from(a.carpeta.trim());
        egui::ScrollArea::vertical().id_salt("planos").max_height(230.0).auto_shrink([false, true]).show_rows(ui, 20.0, visibles.len(), |ui, rango| {
            for k in rango {
                let i = visibles[k];
                let rel = a.planos[i].0.strip_prefix(&base).unwrap_or(&a.planos[i].0).to_string_lossy().to_string();
                ui.add_enabled(!corriendo, egui::Checkbox::new(&mut a.planos[i].1, rel));
            }
        });
        ui.separator();
        ui.horizontal(|ui| {
            ui.label("log en");
            ui.add_enabled(!corriendo, egui::TextEdit::singleline(&mut a.log_dir).desired_width(480.0));
            if ui.add_enabled(!corriendo, egui::Button::new("Examinar…")).on_hover_text("Carpeta del log. No se permiten las carpetas protegidas (PEGCRAFT_PROTEGIDAS o %APPDATA%\\pegcraft\\protegidas.txt).").clicked() {
                if let Some(p) = rfd::FileDialog::new().pick_folder() { a.log_dir = p.to_string_lossy().into(); }
            }
        });
        ui.horizontal(|ui| {
            ui.label("fotogramas").on_hover_text("muestra = primero, medio y último · todos · A:B · n,m,k");
            ui.add_enabled(!corriendo, egui::TextEdit::singleline(&mut a.fotogramas).desired_width(100.0));
            ui.add_enabled(!corriendo, egui::Checkbox::new(&mut a.compartible, "Log para compartir")).on_hover_text(
                "Escribe además *_compartible.json: solo categoría, clave (tipo de nodo, atributo, tipo de columna, modo de mezcla…), conteos y versiones. Sin rutas, ni nombres de escena, nodo o columna, ni mensajes de error.\nSe verifica al terminar (python -m pegcraft analizar --verificar) y, si falla, no se deja el archivo.");
            if ui.add_enabled(!corriendo && sel > 0, egui::Button::new(format!("Analizar {sel}"))).clicked() { a.lanzar(ctx); }
            if ui.add_enabled(corriendo, egui::Button::new("Cancelar")).clicked() { a.cancelar.store(true, Ordering::Relaxed); }
        });
        let (fase, hecho, total, actual, base_log, resumen) = {
            let t = a.trabajo.lock().unwrap();
            (t.fase.clone(), t.hecho, t.total, t.actual.clone(), t.base.clone(), t.resumen.clone())
        };
        match &fase {
            Fase::Corriendo => {
                ui.add(egui::ProgressBar::new(if total > 0 { hecho as f32 / total as f32 } else { 0.0 }).text(format!("{hecho}/{total} · {actual}")));
                ctx.request_repaint_after(Duration::from_millis(250));
            }
            Fase::Error(e) => { ui.colored_label(egui::Color32::from_rgb(240, 110, 90), format!("{e}")); }
            _ => {}
        }
        if let Some(r) = &resumen {
            ui.separator();
            ui.strong(if r.terminado { "Resumen" } else { "Resumen parcial" });
            ui.label(format!("{} escena(s): {} con hallazgos, {} con error de lectura · {} hallazgos distintos · {:.1} s por escena (máx. {:.1} s)", r.escenas, r.con_hallazgos, r.con_error, r.distintos, r.t_medio, r.t_max));
            ui.horizontal_wrapped(|ui| {
                for (c, claves, esc, _n) in &r.por_categoria { ui.label(egui::RichText::new(format!("{c}: {claves} ({esc} esc.)")).small()); }
            });
            ui.weak("más frecuentes (escenas · categoría / clave)");
            egui::ScrollArea::vertical().id_salt("top").max_height(150.0).auto_shrink([false, true]).show(ui, |ui| {
                for (c, k, esc, n) in r.top.iter().take(15) { ui.label(format!("{esc:>4} esc · {n:>6} · {c} / {k}")); }
            });
            ui.horizontal(|ui| {
                if ui.button("Abrir log").on_hover_text("abre el resumen .md").clicked() { abrir_con_el_sistema(&base_log.with_extension("md"), false); }
                if ui.button("Abrir carpeta").clicked() { abrir_con_el_sistema(&base_log.with_extension("jsonl"), true); }
            });
            let comp = PathBuf::from(format!("{}_compartible.json", base_log.display()));
            if comp.is_file() { ui.weak(format!("Para compartir (verificado): {}", comp.display())); }
        }
    });
    a.abierto = abierto;
}
