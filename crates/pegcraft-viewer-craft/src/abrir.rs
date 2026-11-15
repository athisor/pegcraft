// Archivo > Abrir escena: hornea un rango de fotogramas de un .xstage en segundo plano (EN SERIE, un proceso a la vez) llamando al paquete Python
// (`python -m pegcraft hornear`, `scripts\grafo_visor.py`) y devuelve la carpeta para que el visor la cargue. SOLO LECTURA sobre el .xstage:
// lo que se escribe va bajo . o en la carpeta que elija el usuario, nunca en las carpetas de producción protegidas.
use std::{
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::{atomic::{AtomicBool, Ordering}, Arc, Mutex},
    time::Duration,
};

/// Dónde están Python, el código Python y la carpeta de trabajo. Dos modos:
/// - paquete: junto al exe hay `python\python.exe` (Python embebido) y `app\` (pegcraft, sightread, scripts): se usa ese Python con cwd = `app`,
///   y el trabajo por omisión va a `%LOCALAPPDATA%\pegcraft\trabajo` (la carpeta del zip puede ser de solo lectura);
/// - repo: `PEGCRAFT_PY` o `python`, cwd = `.` (el visor se ejecuta desde la raíz del repositorio) y el trabajo en `.\trabajo`.
pub struct Entorno {
    pub paquete: bool,
    pub py: String,
    pub raiz: String,
    pub trabajo: PathBuf,
}
pub fn entorno() -> &'static Entorno {
    static E: std::sync::OnceLock<Entorno> = std::sync::OnceLock::new();
    E.get_or_init(|| {
        let dir = std::env::current_exe().ok().and_then(|e| e.parent().map(|p| p.to_path_buf()));
        if let Some(d) = dir {
            let (py, app) = (d.join("python").join("python.exe"), d.join("app"));
            if py.is_file() && app.is_dir() {
                let base = std::env::var_os("LOCALAPPDATA").map(PathBuf::from).unwrap_or_else(std::env::temp_dir);
                return Entorno { paquete: true, py: py.to_string_lossy().into(), raiz: app.to_string_lossy().into(), trabajo: base.join("pegcraft").join("trabajo") };
            }
        }
        let py = std::env::var("PEGCRAFT_PY").ok().filter(|s| !s.trim().is_empty()).unwrap_or_else(|| "python".to_string());
        Entorno { paquete: false, py, raiz: ".".into(), trabajo: PathBuf::from("trabajo") }
    })
}
/// Ruta absoluta (el hijo corre con otro cwd en modo paquete). Si no se puede resolver, queda como vino.
pub fn absoluta(p: &str) -> String {
    std::path::absolute(p).map(|a| a.to_string_lossy().into_owned()).unwrap_or_else(|_| p.to_string())
}
/// Comando de Python listo: cwd, codificación UTF-8 y, en modo paquete, `-X utf8 -B` (el Python embebido ignora las variables PYTHON* y no debe escribir .pyc en la carpeta del paquete).
pub fn comando_py(args: &[String]) -> Command {
    let e = entorno();
    let mut c = Command::new(&e.py);
    c.current_dir(&e.raiz).env("PYTHONIOENCODING", "utf-8");
    if e.paquete { c.args(["-X", "utf8", "-B"]); }
    c.args(args);
    c
}

#[derive(Clone, PartialEq, Debug)]
pub enum Fase {
    Libre,
    Corriendo,
    Listo,
    Error(String),
}
pub struct Trabajo {
    pub fase: Fase,
    pub hecho: usize,
    pub total: usize,
    pub actual: String,
    pub salida: PathBuf,
    pub grafo: Option<PathBuf>,
}
pub enum Orden {
    Nada,
    Cargar(PathBuf, Option<PathBuf>),
}
pub struct Dialogo {
    pub abierto: bool,
    pub xstage: String,
    pub desde: u32,
    pub hasta: u32,
    pub paso: u32,
    pub salida: String,
    pub extra: String,
    pub op: OpcionesHornear,
    pub carpeta: String,
    pub trabajo: Arc<Mutex<Trabajo>>,
    pub cancelar: Arc<AtomicBool>,
    entregado: bool,
}
impl Default for Dialogo {
    fn default() -> Self {
        Dialogo {
            abierto: false, xstage: String::new(), desde: 1, hasta: 1, paso: 1, salida: String::new(), extra: String::new(), op: OpcionesHornear::default(), carpeta: String::new(),
            trabajo: Arc::new(Mutex::new(Trabajo { fase: Fase::Libre, hecho: 0, total: 0, actual: String::new(), salida: PathBuf::new(), grafo: None })),
            cancelar: Arc::new(AtomicBool::new(false)), entregado: true,
        }
    }
}

/// Opciones de `python -m pegcraft hornear` como casillas y listas. Solo se escribe el parámetro cuando difiere del valor por omisión de `hornear`.
pub struct OpcionesHornear {
    pub conectores: bool,
    pub matriz_causal: bool,
    pub deformadores: bool,
    pub gradientes: bool,
    pub glow_suma: bool,
    pub ignorar_opacidad: bool,
    pub z: usize,
    pub apilado: usize,
    pub recortadas: usize,
    pub camara: usize,
    pub carpeta: usize,
    pub excluir: String,
    pub grupo: String,
}
impl Default for OpcionesHornear {
    fn default() -> Self {
        OpcionesHornear {
            conectores: true, matriz_causal: true, deformadores: true, gradientes: true, glow_suma: true, ignorar_opacidad: false,
            z: 0, apilado: 0, recortadas: 0, camara: 0, carpeta: 0, excluir: String::new(), grupo: String::new(),
        }
    }
}
// (parámetro, valores elegibles; el índice 0 es «por omisión» y no escribe nada)
const Z: (&str, &[&str]) = ("--z", &["(por omisión)", "global", "bitmap"]);
const APILADO: (&str, &[&str]) = ("--apilado", &["(por omisión)", "puertos", "lista"]);
const RECORTADAS: (&str, &[&str]) = ("--recortadas", &["(por omisión)", "omitir", "incluir"]);
const CAMARA: (&str, &[&str]) = ("--camara", &["(por omisión)", "metricas", "iso", "anisotropa", "supuesta"]);
const CARPETA: (&str, &[&str]) = ("--carpeta", &["(por omisión)", "real", "elemento"]);
impl OpcionesHornear {
    /// Parámetros de línea de comandos equivalentes a las casillas.
    pub fn args(&self) -> Vec<String> {
        let mut a: Vec<String> = Vec::new();
        let mut no = |activo: bool, p: &str| if !activo { a.push(p.into()); a.push("no".into()); };
        no(self.conectores, "--conectores");
        no(self.matriz_causal, "--matriz-causal");
        no(self.deformadores, "--deformadores");
        no(self.gradientes, "--gradientes");
        no(self.glow_suma, "--glow-suma");
        if self.ignorar_opacidad { a.push("--opacidad".into()); a.push("ignorar".into()); }
        for (i, (p, vals)) in [(self.z, Z), (self.apilado, APILADO), (self.recortadas, RECORTADAS), (self.camara, CAMARA), (self.carpeta, CARPETA)] {
            if i > 0 { a.push(p.into()); a.push(vals[i].into()); }
        }
        if !self.excluir.trim().is_empty() { a.push("--excluir".into()); a.push(self.excluir.trim().into()); }
        if !self.grupo.trim().is_empty() { a.push("--grupo".into()); a.push(self.grupo.trim().into()); }
        a
    }

    fn ui(&mut self, ui: &mut egui::Ui) {
        ui.horizontal_wrapped(|ui| {
            ui.checkbox(&mut self.conectores, "conectores").on_hover_text(
                "Recorre el grafo de imagen por sus conectores (composites, cutters, capas de arte) para decidir qué se dibuja y en qué orden.\nDesmarcado: --conectores no (apilado simple por lista; activa «apilado» y «recortadas»).");
            ui.checkbox(&mut self.matriz_causal, "matriz causal").on_hover_text(
                "Matrices propias de pegcraft (aspecto de la escena, sesgo, constraints y cámara).\nDesmarcado: --matriz-causal no (usa las matrices del evaluador del lector).");
            ui.checkbox(&mut self.deformadores, "deformadores").on_hover_text("Aplica los deformadores (Offset/Curve) a los dibujos.\nDesmarcado: --deformadores no.");
            ui.checkbox(&mut self.gradientes, "degradados").on_hover_text("Rellenos degradados (lineales y radiales) como degradados SVG.\nDesmarcado: --gradientes no (color plano).");
            ui.checkbox(&mut self.glow_suma, "glow aditivo").on_hover_text("Las piezas que pasan por un GLOW aditivo se suman por canal al componer.\nDesmarcado: --glow-suma no. Sin GLOW en la escena no cambia nada.");
            ui.checkbox(&mut self.ignorar_opacidad, "ignorar opacidad").on_hover_text("Dibuja todo opaco, sin leer la opacidad de los READ.\nMarcado: --opacidad ignorar.");
        });
        let combo = |ui: &mut egui::Ui, etiqueta: &str, ayuda: &str, sel: &mut usize, vals: &[&str]| {
            egui::ComboBox::from_label(etiqueta).selected_text(vals[*sel]).show_ui(ui, |ui| {
                for (i, v) in vals.iter().enumerate() { ui.selectable_value(sel, i, *v); }
            }).response.on_hover_text(ayuda);
        };
        ui.horizontal_wrapped(|ui| {
            combo(ui, "cámara", "Cómo se pasa de campos a píxeles: «metricas» usa las métricas de la escena (por omisión con matriz causal), «iso» trata X e Y igual (por omisión sin ella), «anisotropa» y «supuesta» son variantes de diagnóstico. → --camara", &mut self.camara, CAMARA.1);
            combo(ui, "Z", "Orden en profundidad: «global» ordena por Z en toda la escena; «bitmap» respeta los bloques de los composites bitmap. → --z", &mut self.z, Z.1);
            combo(ui, "carpeta", "De dónde salen los .tvg: «real» = carpeta del elemento en disco; «elemento» = nombre del elemento. → --carpeta", &mut self.carpeta, CARPETA.1);
        });
        ui.add_enabled_ui(!self.conectores, |ui| {
            ui.horizontal_wrapped(|ui| {
                combo(ui, "apilado", "Solo sin conectores: «puertos» = orden por puertos de los composites; «lista» = orden de la lista de nodos evaluados. → --apilado", &mut self.apilado, APILADO.1);
                combo(ui, "recortadas", "Solo sin conectores: piezas con cutter o matte: «omitir» no las dibuja; «incluir» las dibuja sin recortar. → --recortadas", &mut self.recortadas, RECORTADAS.1);
            });
        });
        ui.horizontal(|ui| {
            ui.label("excluir").on_hover_text("Expresión regular de rutas de nodo que no se dibujan (p. ej. REFERENCIA|GUIAS). Vacío = la de PEGCRAFT_EXCLUIR. → --excluir");
            ui.add(egui::TextEdit::singleline(&mut self.excluir).desired_width(160.0).hint_text("regex"));
            ui.label("grupo").on_hover_text("Solo las piezas cuya ruta empieza así (p. ej. Top/Personaje/). Vacío = toda la escena. → --grupo");
            ui.add(egui::TextEdit::singleline(&mut self.grupo).desired_width(160.0).hint_text("Top/…"));
        });
    }
}

/// Número de fotogramas de la escena: atributo `nbframes` del primer `<scene` del .xstage (solo lectura). None si no se puede leer.
fn n_fotogramas(xstage: &str) -> Option<u32> {
    let texto = std::fs::read_to_string(xstage).ok()?;
    let escena = &texto[texto.find("<scene ")?..];
    let resto = &escena[escena.find("nbframes=\"")? + "nbframes=\"".len()..];
    resto[..resto.find('"')?].trim().parse().ok().filter(|n: &u32| *n >= 1)
}

fn salida_por_omision(xstage: &str) -> PathBuf {
    let p = Path::new(xstage);
    let nombre = p.parent().and_then(|d| d.file_name()).and_then(|n| n.to_str()).unwrap_or("escena");
    let nombre: String = nombre.chars().map(|c| if c.is_alphanumeric() || c == '_' || c == '-' { c } else { '_' }).collect();
    entorno().trabajo.join("visor").join("escenas").join(nombre)
}
/// Carpetas donde el visor nunca escribe (material de producción, solo lectura). Son locales de cada usuario, no del código:
/// la variable `PEGCRAFT_PROTEGIDAS` (separadas por `;`) más las líneas de `%APPDATA%\pegcraft\protegidas.txt` (`#` comenta).
pub fn protegidas() -> Vec<String> {
    let norm = |s: &str| {
        let s = s.trim().to_lowercase().replace('/', "\\");
        if s.ends_with('\\') { s } else { format!("{s}\\") }
    };
    let mut v: Vec<String> = std::env::var("PEGCRAFT_PROTEGIDAS").unwrap_or_default().split(';').filter(|s| !s.trim().is_empty()).map(norm).collect();
    if let Ok(app) = std::env::var("APPDATA") {
        if let Ok(t) = std::fs::read_to_string(Path::new(&app).join("pegcraft").join("protegidas.txt")) {
            v.extend(t.lines().map(|l| l.split('#').next().unwrap_or("")).filter(|l| !l.trim().is_empty()).map(norm));
        }
    }
    v
}
/// La salida puede ir bajo `.` (el repositorio) o en cualquier carpeta absoluta elegida por el usuario, salvo las protegidas. Sin `..`.
pub fn permitida(salida: &Path) -> bool {
    let s = salida.to_string_lossy().to_lowercase().replace('/', "\\");
    if s.contains("..") { return false; }
    if !entorno().paquete && s.starts_with(".\\") { return true; }
    let s = if s.ends_with('\\') { s } else { format!("{s}\\") };
    salida.is_absolute() && !protegidas().iter().any(|p| s.starts_with(p.as_str()))
}

#[cfg(windows)]
pub fn sin_ventana(c: &mut Command) {
    use std::os::windows::process::CommandExt;
    c.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
}
#[cfg(not(windows))]
pub fn sin_ventana(_: &mut Command) {}

fn correr(args: &[String], log: &Path, cancelar: &AtomicBool) -> Result<(), String> {
    let f = std::fs::File::create(log).map_err(|e| e.to_string())?;
    let f2 = f.try_clone().map_err(|e| e.to_string())?;
    let mut c = comando_py(args);
    c.stdout(Stdio::from(f)).stderr(Stdio::from(f2));
    sin_ventana(&mut c);
    let mut h = c.spawn().map_err(|e| format!("no se pudo lanzar {}: {e}", entorno().py))?;
    loop {
        if cancelar.load(Ordering::Relaxed) {
            let _ = h.kill();
            return Err("cancelado".into());
        }
        match h.try_wait() {
            Ok(Some(st)) if st.success() => return Ok(()),
            Ok(Some(st)) => {
                let cola = std::fs::read_to_string(log).unwrap_or_default().lines().rev().take(4).collect::<Vec<_>>().into_iter().rev().collect::<Vec<_>>().join(" | ");
                return Err(format!("salio con {st}: {cola}"));
            }
            Ok(None) => std::thread::sleep(Duration::from_millis(150)),
            Err(e) => return Err(e.to_string()),
        }
    }
}

/// Avance de `hornear-rango`: líneas `fotograma i/M f=N` por stdout (i = cuántos van). None si la línea es otra cosa.
fn avance_de(linea: &str) -> Option<(usize, usize, String)> {
    let r = linea.trim().strip_prefix("fotograma ")?;
    let (par, resto) = r.split_once(' ').unwrap_or((r, ""));
    let (i, m) = par.split_once('/')?;
    Some((i.parse().ok()?, m.parse().ok()?, resto.trim_start_matches("f=").to_string()))
}

/// Como `correr`, pero lee el avance de stdout (lo escribe en `t.hecho`/`t.actual`) y deja stderr en el log.
fn correr_rango(args: &[String], log: &Path, cancelar: &AtomicBool, t: &Arc<Mutex<Trabajo>>, ctx: &egui::Context) -> Result<(), String> {
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
            if let Some((i, m, f)) = avance_de(&l) {
                let mut g = t2.lock().unwrap();
                g.hecho = i;
                if m > 0 { g.total = m; }
                g.actual = format!("fotograma {f}");
                drop(g);
                ctx2.request_repaint();
            }
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
                break Err(format!("salio con {st}: {cola}"));
            }
            Ok(None) => std::thread::sleep(Duration::from_millis(100)),
            Err(e) => break Err(e.to_string()),
        }
    };
    let _ = lector.join();
    r
}

impl Dialogo {
    /// «Abrir…» en dos pasos: elegir el .xstage, elegir la carpeta donde guardar la conversión, y hornear TODOS los fotogramas
    /// con las opciones por omisión. Devuelve false si el usuario canceló alguno de los dos selectores.
    pub fn abrir_rapido(&mut self, ctx: &egui::Context) -> bool {
        let Some(x) = rfd::FileDialog::new().set_title("Abrir escena de Harmony").add_filter("Escena Harmony", &["xstage"]).pick_file() else { return false };
        let Some(c) = rfd::FileDialog::new().set_title("Carpeta donde guardar la conversión").pick_folder() else { return false };
        let xs = x.to_string_lossy().to_string();
        let nombre = x.parent().and_then(|d| d.file_name()).and_then(|n| n.to_str()).unwrap_or("escena").to_string();
        self.xstage = xs.clone();
        self.desde = 1;
        self.hasta = n_fotogramas(&xs).unwrap_or(1);
        self.paso = 1;
        self.salida = c.join(nombre).to_string_lossy().into(); // una subcarpeta con el nombre de la escena dentro de la elegida
        self.abierto = true; // la ventana muestra el avance
        self.lanzar(ctx);
        true
    }
    pub fn corriendo(&self) -> bool { self.trabajo.lock().unwrap().fase == Fase::Corriendo }
    pub fn lanzar(&mut self, ctx: &egui::Context) {
        let salida = if self.salida.trim().is_empty() { salida_por_omision(&self.xstage) } else { PathBuf::from(self.salida.trim()) };
        // el hijo corre con otro cwd en modo paquete: las rutas relativas del usuario se vuelven absolutas aquí
        let salida = if entorno().paquete { PathBuf::from(absoluta(&salida.to_string_lossy())) } else { salida };
        if !Path::new(self.xstage.trim()).is_file() { self.fallo(format!("no existe el .xstage: {}", self.xstage)); return; }
        if !permitida(&salida) { self.fallo(format!("salida no permitida (protegida o con ..): {}", salida.display())); return; }
        let frames: Vec<u32> = (self.desde..=self.hasta.max(self.desde)).step_by(self.paso.max(1) as usize).collect();
        {
            let mut t = self.trabajo.lock().unwrap();
            *t = Trabajo { fase: Fase::Corriendo, hecho: 0, total: frames.len(), actual: "grafo de nodos".into(), salida: salida.clone(), grafo: None };
        }
        self.cancelar.store(false, Ordering::Relaxed);
        self.entregado = false;
        let (xs, extra) = (absoluta(self.xstage.trim()),format!("{} {}", self.op.args().join(" "), self.extra));
        let (desde, hasta, paso) = (self.desde, self.hasta.max(self.desde), self.paso.max(1));
        let (t, cancelar, ctx) = (self.trabajo.clone(), self.cancelar.clone(), ctx.clone());
        std::thread::spawn(move || {
            let fin = |r: Result<(), String>, t: &Arc<Mutex<Trabajo>>| {
                let mut g = t.lock().unwrap();
                g.fase = match r { Ok(()) => Fase::Listo, Err(e) => Fase::Error(e) };
            };
            if let Err(e) = std::fs::create_dir_all(&salida) { fin(Err(e.to_string()), &t); ctx.request_repaint(); return; }
            let grafo = salida.join("grafo.json");
            let r = correr(&[format!("{}\\scripts\\grafo_visor.py", entorno().raiz),xs.clone(), grafo.to_string_lossy().into()], &salida.join("grafo.log"), &cancelar);
            match r {
                Ok(()) => t.lock().unwrap().grafo = Some(grafo),
                Err(e) if e == "cancelado" => { fin(Err(e), &t); ctx.request_repaint(); return; }
                Err(e) => eprintln!("grafo: {e} (se sigue sin vista de nodos)"),
            }
            ctx.request_repaint();
            // UN solo proceso para todo el rango (`hornear-rango`): abre el .xstage una vez y convierte cada .tvg una vez; el avance sale por stdout.
            let mut args: Vec<String> = vec!["-m".into(), "pegcraft".into(), "hornear-rango".into()];
            args.extend(extra.split_whitespace().map(|s| s.to_string()));
            args.extend([xs.clone(), salida.to_string_lossy().into(), "--desde".into(), desde.to_string(), "--hasta".into(), hasta.to_string(), "--paso".into(), paso.to_string()]);
            let r = correr_rango(&args, &salida.join("hornear.log"), &cancelar, &t, &ctx);
            let hecho = t.lock().unwrap().hecho;
            match r {
                // un cancelado con algo horneado se entrega igual (se puede abrir lo que haya)
                Err(e) if e == "cancelado" && hecho > 0 => fin(Ok(()), &t),
                Err(e) => fin(Err(e), &t),
                Ok(()) => fin(Ok(()), &t),
            }
            ctx.request_repaint();
        });
    }
    fn fallo(&mut self, m: String) { self.trabajo.lock().unwrap().fase = Fase::Error(m); }
}

/// ventana de «Abrir escena»; devuelve una orden cuando hay algo que cargar
pub fn mostrar(ctx: &egui::Context, d: &mut Dialogo) -> Orden {
    let mut orden = Orden::Nada;
    // al terminar el horneado se entrega UNA vez
    {
        let t = d.trabajo.lock().unwrap();
        if t.fase == Fase::Listo && !d.entregado {
            d.entregado = true;
            orden = Orden::Cargar(t.salida.clone(), t.grafo.clone());
        }
    }
    if !d.abierto { return orden; }
    let mut abierto = true;
    egui::Window::new("Abrir escena").open(&mut abierto).default_width(560.0).show(ctx, |ui| {
        ui.strong("Escena de Harmony (.xstage) → hornear y abrir");
        ui.weak("Solo lee el .xstage y los .tvg. El horneado corre en serie en segundo plano (≈1–3 s por fotograma) y escribe bajo ..");
        ui.horizontal(|ui| {
            ui.label(".xstage");
            ui.add(egui::TextEdit::singleline(&mut d.xstage).desired_width(380.0).hint_text(r"ruta\escena.xstage"));
            if ui.button("Examinar…").clicked() {
                if let Some(p) = rfd::FileDialog::new().add_filter("Escena Harmony", &["xstage"]).pick_file() {
                    d.xstage = p.to_string_lossy().into();
                    if let Some(n) = n_fotogramas(&d.xstage) { d.desde = 1; d.hasta = n; } // al elegir escena: todos sus fotogramas
                }
            }
        });
        ui.horizontal(|ui| {
            ui.label("fotogramas");
            ui.add(egui::DragValue::new(&mut d.desde).range(1..=100000).prefix("desde "));
            ui.add(egui::DragValue::new(&mut d.hasta).range(1..=100000).prefix("hasta "));
            ui.add(egui::DragValue::new(&mut d.paso).range(1..=1000).prefix("cada "));
            if ui.button("Todos").on_hover_text("del 1 al último fotograma de la escena (nbframes)").clicked() {
                if let Some(n) = n_fotogramas(&d.xstage) { d.desde = 1; d.hasta = n; }
            }
            let n = (d.hasta.max(d.desde) - d.desde) / d.paso.max(1) + 1;
            ui.weak(format!("= {n} fotograma(s)"));
        });
        ui.horizontal(|ui| {
            ui.label("salida");
            let hint = salida_por_omision(&d.xstage).to_string_lossy().to_string();
            ui.add(egui::TextEdit::singleline(&mut d.salida).desired_width(380.0).hint_text(hint));
            if ui.button("Examinar…").on_hover_text("Elegir la carpeta donde se guarda el horneado. No se permite escribir en las carpetas protegidas (PEGCRAFT_PROTEGIDAS o %APPDATA%\\pegcraft\\protegidas.txt).").clicked() {
                if let Some(p) = rfd::FileDialog::new().pick_folder() { d.salida = p.to_string_lossy().into(); }
            }
        });
        ui.separator();
        ui.label("opciones de horneado").on_hover_text("Cada casilla o lista se traduce a un parámetro de `python -m pegcraft hornear`; pasa el ratón por encima para ver qué hace.");
        d.op.ui(ui);
        ui.horizontal(|ui| {
            ui.label("otras").on_hover_text("Parámetros extra escritos a mano, para lo que no tiene casilla (p. ej. --exp sin_capas).");
            ui.add(egui::TextEdit::singleline(&mut d.extra).desired_width(300.0).hint_text("vacío = ninguno"));
        });
        let linea = format!("{} {}", d.op.args().join(" "), d.extra).trim().to_string();
        ui.weak(if linea.is_empty() { "parámetros: (por omisión)".to_string() } else { format!("parámetros: {linea}") });
        ui.separator();
        let (fase, hecho, total, actual) = { let t = d.trabajo.lock().unwrap(); (t.fase.clone(), t.hecho, t.total, t.actual.clone()) };
        ui.horizontal(|ui| {
            let corriendo = fase == Fase::Corriendo;
            if ui.add_enabled(!corriendo && !d.xstage.trim().is_empty(), egui::Button::new("Hornear y abrir")).clicked() { d.lanzar(ctx); }
            if ui.add_enabled(corriendo, egui::Button::new("Cancelar")).clicked() { d.cancelar.store(true, Ordering::Relaxed); }
        });
        match &fase {
            Fase::Corriendo => {
                ui.add(egui::ProgressBar::new(if total > 0 { hecho as f32 / total as f32 } else { 0.0 }).text(format!("{hecho}/{total} · {actual}")));
                ctx.request_repaint_after(Duration::from_millis(250));
            }
            Fase::Listo => { ui.label(format!("Listo: {hecho}/{total} fotogramas horneados.")); }
            Fase::Error(e) => { ui.colored_label(egui::Color32::from_rgb(240, 110, 90), format!("Error: {e}")); }
            Fase::Libre => {}
        }
        ui.separator();
        ui.strong("Carpeta ya horneada");
        ui.horizontal(|ui| {
            ui.add(egui::TextEdit::singleline(&mut d.carpeta).desired_width(380.0).hint_text(r"carpeta con escena.json o escena_f*.json o subcarpetas f0001…"));
            if ui.button("Examinar…").clicked() {
                if let Some(p) = rfd::FileDialog::new().pick_folder() { d.carpeta = p.to_string_lossy().into(); }
            }
            if ui.add_enabled(!d.carpeta.trim().is_empty(), egui::Button::new("Abrir")).clicked() {
                let c = PathBuf::from(d.carpeta.trim());
                let g = [c.join("grafo.json"), c.parent().map(|p| p.join("grafo.json")).unwrap_or_default()].into_iter().find(|p| p.is_file());
                orden = Orden::Cargar(c, g);
            }
        });
    });
    d.abierto = abierto;
    orden
}
