// Archivo > Abrir escena: hornea un rango de fotogramas de un .xstage en segundo plano (EN SERIE, un proceso a la vez) llamando al paquete Python
// (`python -m pegcraft hornear`, `scripts\grafo_visor.py`) y devuelve la carpeta para que el visor la cargue. SOLO LECTURA sobre el .xstage:
// todo lo que se escribe va bajo . (se rechaza cualquier otra salida: ninguna otra carpeta).
use std::{
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::{atomic::{AtomicBool, Ordering}, Arc, Mutex},
    time::Duration,
};

pub const RAIZ: &str = "."; // el visor se ejecuta desde la raiz del repositorio
pub const PY: &str = r"python";

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
    pub carpeta: String,
    pub trabajo: Arc<Mutex<Trabajo>>,
    pub cancelar: Arc<AtomicBool>,
    entregado: bool,
}
impl Default for Dialogo {
    fn default() -> Self {
        Dialogo {
            abierto: false, xstage: String::new(), desde: 1, hasta: 1, paso: 1, salida: String::new(), extra: String::new(), carpeta: String::new(),
            trabajo: Arc::new(Mutex::new(Trabajo { fase: Fase::Libre, hecho: 0, total: 0, actual: String::new(), salida: PathBuf::new(), grafo: None })),
            cancelar: Arc::new(AtomicBool::new(false)), entregado: true,
        }
    }
}

fn salida_por_omision(xstage: &str) -> PathBuf {
    let p = Path::new(xstage);
    let nombre = p.parent().and_then(|d| d.file_name()).and_then(|n| n.to_str()).unwrap_or("escena");
    let nombre: String = nombre.chars().map(|c| if c.is_alphanumeric() || c == '_' || c == '-' { c } else { '_' }).collect();
    PathBuf::from(RAIZ).join("trabajo").join("visor").join("escenas").join(nombre)
}
fn permitida(salida: &Path) -> bool {
    let s = salida.to_string_lossy().to_lowercase().replace('/', "\\");
    s.starts_with(&format!("{}\\", RAIZ.to_lowercase())) && !s.contains("..")
}

#[cfg(windows)]
fn sin_ventana(c: &mut Command) {
    use std::os::windows::process::CommandExt;
    c.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
}
#[cfg(not(windows))]
fn sin_ventana(_: &mut Command) {}

fn correr(args: &[String], log: &Path, cancelar: &AtomicBool) -> Result<(), String> {
    let f = std::fs::File::create(log).map_err(|e| e.to_string())?;
    let f2 = f.try_clone().map_err(|e| e.to_string())?;
    let mut c = Command::new(PY);
    c.current_dir(RAIZ).env("PYTHONIOENCODING", "utf-8").args(args).stdout(Stdio::from(f)).stderr(Stdio::from(f2));
    sin_ventana(&mut c);
    let mut h = c.spawn().map_err(|e| format!("no se pudo lanzar {PY}: {e}"))?;
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

impl Dialogo {
    pub fn corriendo(&self) -> bool { self.trabajo.lock().unwrap().fase == Fase::Corriendo }
    pub fn lanzar(&mut self, ctx: &egui::Context) {
        let salida = if self.salida.trim().is_empty() { salida_por_omision(&self.xstage) } else { PathBuf::from(self.salida.trim()) };
        if !Path::new(self.xstage.trim()).is_file() { self.fallo(format!("no existe el .xstage: {}", self.xstage)); return; }
        if !permitida(&salida) { self.fallo(format!("la salida debe estar bajo {RAIZ}\\ (no se escribe en otras carpetas): {}", salida.display())); return; }
        let frames: Vec<u32> = (self.desde..=self.hasta.max(self.desde)).step_by(self.paso.max(1) as usize).collect();
        {
            let mut t = self.trabajo.lock().unwrap();
            *t = Trabajo { fase: Fase::Corriendo, hecho: 0, total: frames.len(), actual: "grafo de nodos".into(), salida: salida.clone(), grafo: None };
        }
        self.cancelar.store(false, Ordering::Relaxed);
        self.entregado = false;
        let (xs, extra) = (self.xstage.trim().to_string(), self.extra.clone());
        let (t, cancelar, ctx) = (self.trabajo.clone(), self.cancelar.clone(), ctx.clone());
        std::thread::spawn(move || {
            let fin = |r: Result<(), String>, t: &Arc<Mutex<Trabajo>>| {
                let mut g = t.lock().unwrap();
                g.fase = match r { Ok(()) => Fase::Listo, Err(e) => Fase::Error(e) };
            };
            if let Err(e) = std::fs::create_dir_all(&salida) { fin(Err(e.to_string()), &t); ctx.request_repaint(); return; }
            let grafo = salida.join("grafo.json");
            let r = correr(&[format!("{RAIZ}\\scripts\\grafo_visor.py"), xs.clone(), grafo.to_string_lossy().into()], &salida.join("grafo.log"), &cancelar);
            match r {
                Ok(()) => t.lock().unwrap().grafo = Some(grafo),
                Err(e) if e == "cancelado" => { fin(Err(e), &t); ctx.request_repaint(); return; }
                Err(e) => eprintln!("grafo: {e} (se sigue sin vista de nodos)"),
            }
            ctx.request_repaint();
            for f in frames {
                {
                    let mut g = t.lock().unwrap();
                    g.actual = format!("fotograma {f}");
                }
                ctx.request_repaint();
                let dir = salida.join(format!("f{f:04}"));
                let mut args: Vec<String> = vec!["-m".into(), "pegcraft".into(), "hornear".into()];
                args.extend(extra.split_whitespace().map(|s| s.to_string()));
                args.extend([xs.clone(), f.to_string(), dir.to_string_lossy().into()]);
                if let Err(e) = correr(&args, &salida.join(format!("hornear_f{f:04}.log")), &cancelar) {
                    let hecho = t.lock().unwrap().hecho;
                    // un cancelado con algo horneado se entrega igual (se puede abrir lo que haya)
                    if e == "cancelado" && hecho > 0 { fin(Ok(()), &t); } else { fin(Err(e), &t); }
                    ctx.request_repaint();
                    return;
                }
                t.lock().unwrap().hecho += 1;
                ctx.request_repaint();
            }
            fin(Ok(()), &t);
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
        ui.weak("Solo lee el .xstage y los .tvg. El horneado corre en serie en segundo plano (≈15–40 s por fotograma) y escribe bajo ..");
        ui.horizontal(|ui| {
            ui.label(".xstage");
            ui.add(egui::TextEdit::singleline(&mut d.xstage).desired_width(380.0).hint_text(r"ruta\escena.xstage"));
            if ui.button("Examinar…").clicked() {
                if let Some(p) = rfd::FileDialog::new().add_filter("Escena Harmony", &["xstage"]).pick_file() { d.xstage = p.to_string_lossy().into(); }
            }
        });
        ui.horizontal(|ui| {
            ui.label("fotogramas");
            ui.add(egui::DragValue::new(&mut d.desde).range(1..=100000).prefix("desde "));
            ui.add(egui::DragValue::new(&mut d.hasta).range(1..=100000).prefix("hasta "));
            ui.add(egui::DragValue::new(&mut d.paso).range(1..=1000).prefix("cada "));
            let n = (d.hasta.max(d.desde) - d.desde) / d.paso.max(1) + 1;
            ui.weak(format!("= {n} fotograma(s)"));
        });
        ui.horizontal(|ui| {
            ui.label("salida");
            let hint = salida_por_omision(&d.xstage).to_string_lossy().to_string();
            ui.add(egui::TextEdit::singleline(&mut d.salida).desired_width(480.0).hint_text(hint));
        });
        ui.horizontal(|ui| {
            ui.label("opciones de `hornear`");
            ui.add(egui::TextEdit::singleline(&mut d.extra).desired_width(380.0).hint_text("p. ej. --camara metricas --recortadas incluir (vacío = por omisión)"));
        });
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
