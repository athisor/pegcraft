// Vista de nodos (solo lectura) del grafo de la escena, como la Node View de Harmony: posiciones del archivo, backdrops con titulo y color,
// grupos navegables (doble clic) con breadcrumb, cables Bezier con puertos numerados. Patron de camara/tarjetas/cables imitado de
// materialcraft/crates/ui-egui/src/graph; codigo propio.
// Datos: trabajo\visor\grafo.json (scripts\grafo_visor.py, motor lector_xstage): px,py = <node pos> del .xstage, backdrops por grupo, cables LITERALES.
// Si en un grupo las posiciones del archivo estan degeneradas (muchos nodos en el mismo punto, p. ej. escenas generadas por script) se usa el layout
// automatico por capas (x,y) solo para ese grupo, y se avisa.
use egui::{epaint::CubicBezierShape, pos2, vec2, Align2, Color32, FontId, Pos2, Rect, Sense, Stroke, StrokeKind, Vec2};
use std::collections::{HashMap, HashSet};

pub struct NodoG {
    pub id: String,
    pub nombre: String,
    pub tipo: String,
    pub apagado: bool,
    pub x: f32, // layout automatico (columna, rango)
    pub y: f32,
    pub px: f32, // posicion en el .xstage
    pub py: f32,
    pub ent: u32,
    pub sal: u32,
}
pub struct CableG {
    pub de: String,
    pub pd: u32,
    pub a: String,
    pub pa: u32,
}
pub struct Fondo {
    pub titulo: String,
    pub color: Color32,
    pub rect: Rect, // en unidades de la vista nodal de Harmony
    pub nodos: usize,
}
#[derive(Default)]
pub struct GrupoG {
    pub nodos: Vec<NodoG>,
    pub cables: Vec<CableG>,
    pub fondos: Vec<Fondo>,
    pub idx: HashMap<String, usize>,
    pub degenerado: bool, // posiciones del archivo inservibles
}
pub struct Grafo {
    pub escena: String,
    pub raiz: String,
    pub grupos: HashMap<String, GrupoG>,
}

fn color_hex(s: &str) -> Color32 {
    let s = s.trim_start_matches('#');
    let v = u32::from_str_radix(s, 16).unwrap_or(0x555555FF);
    if s.len() == 8 { Color32::from_rgba_unmultiplied((v >> 24) as u8, (v >> 16) as u8, (v >> 8) as u8, v as u8) } else { Color32::from_rgb((v >> 16) as u8, (v >> 8) as u8, v as u8) }
}

pub fn cargar(ruta: &std::path::Path) -> Result<Grafo, String> {
    let j: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(ruta).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
    let mut grupos = HashMap::new();
    let vacio = vec![];
    for (k, g) in j["grupos"].as_object().ok_or("sin grupos")? {
        let mut gr = GrupoG::default();
        for n in g["nodos"].as_array().unwrap_or(&vacio) {
            gr.idx.insert(n["id"].as_str().unwrap_or("").to_string(), gr.nodos.len());
            gr.nodos.push(NodoG {
                id: n["id"].as_str().unwrap_or("").to_string(),
                nombre: n["nombre"].as_str().unwrap_or("").to_string(),
                tipo: n["tipo"].as_str().unwrap_or("").to_string(),
                apagado: n["apagado"].as_bool().unwrap_or(false),
                x: n["x"].as_f64().unwrap_or(0.0) as f32,
                y: n["y"].as_f64().unwrap_or(0.0) as f32,
                px: n["px"].as_f64().unwrap_or(0.0) as f32,
                py: n["py"].as_f64().unwrap_or(0.0) as f32,
                ent: n["entradas"].as_u64().unwrap_or(0) as u32,
                sal: n["salidas"].as_u64().unwrap_or(0) as u32,
            });
        }
        for c in g["cables"].as_array().unwrap_or(&vacio) {
            gr.cables.push(CableG { de: c["de"].as_str().unwrap_or("").to_string(), pd: c["pd"].as_u64().unwrap_or(0) as u32, a: c["a"].as_str().unwrap_or("").to_string(), pa: c["pa"].as_u64().unwrap_or(0) as u32 });
        }
        for b in g["backdrops"].as_array().unwrap_or(&vacio) {
            let r: Vec<f32> = b["rect"].as_array().map(|a| a.iter().filter_map(|x| x.as_f64()).map(|x| x as f32).collect()).unwrap_or_default();
            if r.len() == 4 {
                gr.fondos.push(Fondo { titulo: b["titulo"].as_str().unwrap_or("").to_string(), color: color_hex(b["color"].as_str().unwrap_or("")), rect: Rect::from_min_max(pos2(r[0], r[1]), pos2(r[2], r[3])), nodos: b["nodos"].as_array().map(|a| a.len()).unwrap_or(0) });
            }
        }
        // posiciones degeneradas: menos del 60 % de puntos distintos (con >2 nodos)
        let distintos: HashSet<(i32, i32)> = gr.nodos.iter().map(|n| (n.px.round() as i32, n.py.round() as i32)).collect();
        gr.degenerado = gr.nodos.len() > 2 && distintos.len() * 10 < gr.nodos.len() * 6;
        grupos.insert(k.clone(), gr);
    }
    Ok(Grafo { escena: j["escena"].as_str().unwrap_or("").to_string(), raiz: j["raiz"].as_str().unwrap_or("Top").to_string(), grupos })
}

fn color_tipo(t: &str) -> Color32 {
    let u = t.to_uppercase();
    if u.contains("READ") { Color32::from_rgb(120, 84, 176) }
    else if u.contains("CUTTER") { Color32::from_rgb(200, 120, 40) }
    else if u.contains("PEG") { Color32::from_rgb(60, 140, 90) }
    else if u.contains("COMPOSITE") { Color32::from_rgb(50, 110, 180) }
    else if u.contains("GROUP") { Color32::from_rgb(170, 150, 60) }
    else if u.contains("CURVE") || u.contains("OFFSET") || u.contains("DEFORM") || u.contains("KINEMATIC") { Color32::from_rgb(190, 70, 60) }
    else if u.contains("MULTI") { Color32::from_rgb(80, 130, 140) }
    else { Color32::from_rgb(100, 100, 108) }
}

pub struct Vista {
    pub grupo: String,
    pub centro: Vec2,
    pub zoom: f32,
    pub sel: Option<String>,
    pub ajustar: bool,
    pub harmony: bool, // preferir las posiciones del .xstage (si el grupo las tiene utilizables)
    pub angulado: bool, // estilo de cable: angulado (con tramos rectos) o curvo; Harmony: «Cable Style · Angled»
    pub raiz: String,
    pub centrar: bool, // «Center on Selection»
}

fn pastel(c: Color32) -> Color32 {
    let m = |v: u8| (v as f32 + (255.0 - v as f32) * 0.55) as u8;
    Color32::from_rgb(m(c.r()), m(c.g()), m(c.b()))
}

// layout efectivo de un grupo: (usa posiciones de Harmony?)
fn usa_harmony(v: &Vista, gr: &GrupoG) -> bool { v.harmony && !gr.degenerado }
// esquina superior izquierda y tamano de un nodo, en unidades del mundo
const AUTO: (f32, f32, f32, f32) = (190.0, 90.0, 150.0, 40.0); // DX, DY, ancho, alto
const HNW: f32 = 150.0; // tamano de tarjeta en unidades de Harmony (pos = centro del nodo; SUPUESTO)
const HNH: f32 = 36.0;
fn caja_mundo(n: &NodoG, harm: bool) -> Rect {
    if harm { Rect::from_center_size(pos2(n.px, n.py), vec2(HNW, HNH)) } else { Rect::from_min_size(pos2(n.x * AUTO.0, n.y * AUTO.1), vec2(AUTO.2, AUTO.3)) }
}

impl Vista {
    pub fn nueva(raiz: &str) -> Self {
        Vista { grupo: raiz.to_string(), centro: Vec2::ZERO, zoom: 0.5, sel: None, ajustar: true, harmony: true, angulado: true, raiz: raiz.to_string(), centrar: false }
    }
    /// salta al grupo del nodo y lo selecciona (para enlazar con la seleccion de capas)
    pub fn ir_a(&mut self, g: &Grafo, id: &str) -> bool {
        let grp = id.rsplit_once('/').map(|x| x.0).unwrap_or("");
        if let Some(gr) = g.grupos.get(grp) {
            if let Some(&i) = gr.idx.get(id) {
                self.grupo = grp.to_string();
                self.sel = Some(id.to_string());
                self.centro = caja_mundo(&gr.nodos[i], usa_harmony(self, gr)).center().to_vec2();
                self.zoom = 0.9;
                self.ajustar = false;
                return true;
            }
        }
        false
    }
}

/// devuelve el id de un READ pulsado (para seleccionar su capa)
pub fn mostrar(ui: &mut egui::Ui, g: &Grafo, v: &mut Vista) -> Option<String> {
    let mut pulsado = None;
    let Some(gr) = g.grupos.get(&v.grupo) else {
        ui.label(format!("grupo {} sin datos", v.grupo));
        return None;
    };
    let harm = usa_harmony(v, gr);
    ui.horizontal_wrapped(|ui| {
        if ui.button("⬆ Subir").clicked() {
            if let Some((p, _)) = v.grupo.rsplit_once('/') {
                if g.grupos.contains_key(p) {
                    let hijo = v.grupo.clone();
                    v.grupo = p.to_string();
                    v.sel = Some(hijo);
                    v.ajustar = true;
                }
            }
        }
        if ui.button("Root").clicked() { v.grupo = v.raiz.clone(); v.sel = None; v.ajustar = true; }
        if ui.button("Mostrar todo").clicked() { v.ajustar = true; }
        if ui.add_enabled(v.sel.is_some(), egui::Button::new("Centrar selección")).clicked() { v.centrar = true; }
        if ui.checkbox(&mut v.harmony, "Posiciones de Harmony").changed() { v.ajustar = true; }
        ui.checkbox(&mut v.angulado, "Cable angulado");
        // breadcrumb: cada tramo salta a su grupo
        let mut acum = String::new();
        let mut destino = None;
        for (i, seg) in v.grupo.split('/').enumerate() {
            if i > 0 { acum.push('/'); }
            acum.push_str(seg);
            if i > 0 { ui.weak("›"); }
            if ui.small_button(seg).clicked() && g.grupos.contains_key(&acum) { destino = Some(acum.clone()); }
        }
        if let Some(d) = destino { v.grupo = d; v.sel = None; v.ajustar = true; }
        let sin_cables = gr.nodos.iter().filter(|n| !gr.cables.iter().any(|c| c.de == n.id || c.a == n.id)).count();
        ui.weak(format!("{} nodos · {} cables · {} sin conectar · {} backdrops{}", gr.nodos.len(), gr.cables.len(), sin_cables, gr.fondos.len(),
            if gr.degenerado && v.harmony { " · posiciones del archivo degeneradas → layout automático" } else if !harm { " · layout automático" } else { "" }));
    });
    let alto_info = 54.0;
    let avail = vec2(ui.available_width(), (ui.available_height() - alto_info).max(100.0));
    let (rect, resp) = ui.allocate_exact_size(avail, Sense::click_and_drag());
    if v.ajustar && !gr.nodos.is_empty() {
        let mut b = Rect::NOTHING;
        for n in &gr.nodos { b = b.union(caja_mundo(n, harm)); }
        if harm { for f in &gr.fondos { b = b.union(f.rect); } }
        let b = b.expand(30.0);
        v.zoom = (rect.width() / b.width()).min(rect.height() / b.height()).clamp(0.02, 1.5);
        v.centro = b.center().to_vec2();
        v.ajustar = false;
    }
    if v.centrar {
        if let Some(&i) = v.sel.as_ref().and_then(|s| gr.idx.get(s)) { v.centro = caja_mundo(&gr.nodos[i], harm).center().to_vec2(); }
        v.centrar = false;
    }
    if resp.dragged() { v.centro -= resp.drag_delta() / v.zoom; }
    if resp.hovered() {
        let sc = ui.input(|i| i.smooth_scroll_delta.y);
        if sc != 0.0 { v.zoom = (v.zoom * (sc * 0.002).exp()).clamp(0.02, 3.0); }
    }
    let z = v.zoom;
    let c = rect.center();
    let cen = v.centro;
    let a_s = |w: Pos2| c + (w.to_vec2() - cen) * z;
    let rect_s = |r: Rect| Rect::from_min_max(a_s(r.min), a_s(r.max));
    let p = ui.painter_at(rect);
    p.rect_filled(rect, 0.0, Color32::from_rgb(30, 31, 36));
    let visible = rect.expand(80.0);
    // backdrops (detras de todo); solo con posiciones de Harmony, donde su rectangulo tiene sentido
    if harm {
        for f in &gr.fondos {
            let r = rect_s(f.rect);
            if !r.intersects(visible) { continue; }
            let [cr, cg, cb, _] = f.color.to_array();
            p.rect_filled(r, 6.0 * z.min(1.0), Color32::from_rgba_unmultiplied(cr, cg, cb, 70));
            p.rect_stroke(r, 6.0 * z.min(1.0), Stroke::new(1.5, Color32::from_rgba_unmultiplied(cr, cg, cb, 200)), StrokeKind::Inside);
            if !f.titulo.is_empty() && z > 0.08 {
                p.text(r.left_top() + vec2(6.0, 4.0), Align2::LEFT_TOP, &f.titulo, FontId::proportional((15.0 * z).clamp(9.0, 22.0)), Color32::from_gray(235));
            }
        }
    }
    let caja = |n: &NodoG| rect_s(caja_mundo(n, harm));
    let puerto_sal = |n: &NodoG, k: u32| { let r = caja(n); pos2(r.left() + r.width() * (k as f32 + 0.5) / n.sal.max(1) as f32, r.bottom()) };
    let puerto_ent = |n: &NodoG, k: u32| { let r = caja(n); pos2(r.left() + r.width() * (k as f32 + 0.5) / n.ent.max(1) as f32, r.top()) };
    let sel = v.sel.clone();
    for cb in &gr.cables {
        let (Some(&i), Some(&j)) = (gr.idx.get(&cb.de), gr.idx.get(&cb.a)) else { continue };
        let (p0, p1) = (puerto_sal(&gr.nodos[i], cb.pd), puerto_ent(&gr.nodos[j], cb.pa));
        if !Rect::from_two_pos(p0, p1).intersects(visible) { continue; }
        let resaltado = sel.as_deref() == Some(cb.de.as_str()) || sel.as_deref() == Some(cb.a.as_str());
        let col = if resaltado { Color32::from_rgb(255, 220, 90) } else { Color32::from_rgb(0, 170, 220) };
        let st = Stroke::new(if resaltado { 2.5 } else { 1.5 }, col);
        if v.angulado {
            let s = 10.0 * z; // tramo corto vertical en cada puerto y recta entre ellos, como el «Angled» de Harmony
            p.add(egui::Shape::line(vec![p0, p0 + vec2(0.0, s), p1 - vec2(0.0, s), p1], st));
        } else {
            let dy = ((p1.y - p0.y).abs() * 0.5).max(30.0 * z);
            p.add(CubicBezierShape::from_points_stroke([p0, p0 + vec2(0.0, dy), p1 - vec2(0.0, dy), p1], false, Color32::TRANSPARENT, st));
        }
    }
    let click = if resp.clicked() || resp.double_clicked() { resp.interact_pointer_pos() } else { None };
    let mut entrar: Option<String> = None;
    for n in &gr.nodos {
        let r = caja(n);
        if !r.intersects(visible) { continue; }
        let es_sel = sel.as_deref() == Some(n.id.as_str());
        let es_grupo = n.tipo.to_uppercase().contains("GROUP");
        let mut col = pastel(color_tipo(&n.tipo));
        if n.apagado { col = col.gamma_multiply(0.5); }
        p.rect_filled(r, 4.0 * z.min(1.0), col);
        p.rect_stroke(r, 4.0 * z.min(1.0), Stroke::new(if es_sel { 3.0 } else { 1.0 }, if es_sel { Color32::from_rgb(255, 220, 90) } else { Color32::BLACK }), StrokeKind::Inside);
        if es_grupo { // un grupo se dibuja como carpeta: pestana + conteo de su contenido
            let t = Rect::from_min_size(r.left_top() - vec2(0.0, 6.0 * z), vec2(r.width() * 0.4, 6.0 * z));
            p.rect_filled(t, 2.0, col);
        }
        if z > 0.12 {
            let pt = p.with_clip_rect(r.shrink(1.0));
            let sub = if es_grupo { format!("GROUP · {} nodos", g.grupos.get(&n.id).map(|x| x.nodos.len()).unwrap_or(0)) } else { n.tipo.clone() };
            // tarjeta como la Node View de Harmony: cuadro amarillo (propiedades), triangulo (expandir) y nombre a la izquierda
            let lado = 11.0 * z;
            let cy = r.center().y - if z > 0.35 { 5.0 * z } else { 0.0 };
            let q = Rect::from_center_size(pos2(r.left() + 10.0 * z, cy), vec2(lado, lado));
            pt.rect_filled(q, 1.0, Color32::from_rgb(255, 205, 0));
            pt.rect_stroke(q, 1.0, Stroke::new(1.0, Color32::from_rgb(120, 90, 0)), StrokeKind::Inside);
            let tx = r.left() + 22.0 * z;
            pt.add(egui::Shape::convex_polygon(vec![pos2(tx, cy - 4.0 * z), pos2(tx, cy + 4.0 * z), pos2(tx + 6.0 * z, cy)], Color32::from_gray(40), Stroke::NONE));
            pt.text(pos2(tx + 11.0 * z, cy), Align2::LEFT_CENTER, &n.nombre, FontId::proportional((13.0 * z).clamp(6.0, 18.0)), Color32::from_gray(25));
            if z > 0.35 { pt.text(pos2(r.left() + 10.0 * z, r.center().y + 10.0 * z), Align2::LEFT_CENTER, sub, FontId::proportional((9.5 * z).clamp(5.0, 13.0)), Color32::from_gray(70)); }
        }
        if z > 0.45 {
            for k in 0..n.ent {
                let q = puerto_ent(n, k);
                p.rect_filled(Rect::from_center_size(q, vec2(7.0, 7.0) * z.min(1.2)), 0.0, Color32::from_rgb(0, 170, 220));
                p.text(q - vec2(0.0, 8.0 * z), Align2::CENTER_BOTTOM, k.to_string(), FontId::proportional(9.0 * z.min(1.2)), Color32::from_gray(190));
            }
            for k in 0..n.sal {
                let q = puerto_sal(n, k);
                p.rect_filled(Rect::from_center_size(q, vec2(7.0, 7.0) * z.min(1.2)), 0.0, Color32::from_rgb(0, 170, 220));
                p.text(q + vec2(0.0, 8.0 * z), Align2::CENTER_TOP, k.to_string(), FontId::proportional(9.0 * z.min(1.2)), Color32::from_rgb(240, 190, 80));
            }
        }
        if let Some(cp) = click {
            if r.contains(cp) {
                v.sel = Some(n.id.clone());
                if n.tipo.to_uppercase().contains("READ") { pulsado = Some(n.id.clone()); }
                if resp.double_clicked() && es_grupo { entrar = Some(n.id.clone()); }
            }
        }
    }
    if let Some(e) = entrar {
        if g.grupos.contains_key(&e) { v.grupo = e; v.sel = None; v.ajustar = true; }
    }
    let txt = match v.sel.as_ref().and_then(|s| gr.idx.get(s)) {
        Some(&i) => {
            let n = &gr.nodos[i];
            let nombre = |id: &str| gr.idx.get(id).map(|&k| gr.nodos[k].nombre.clone()).unwrap_or_else(|| id.to_string());
            let ent: Vec<String> = gr.cables.iter().filter(|c| c.a == n.id).map(|c| format!("[{}]←{}:{}", c.pa, nombre(&c.de), c.pd)).collect();
            let sal: Vec<String> = gr.cables.iter().filter(|c| c.de == n.id).map(|c| format!("{}→{}[{}]", c.pd, nombre(&c.a), c.pa)).collect();
            format!("{} · {} · pos ({:.0}, {:.0}) · entradas: {} · salidas: {}", n.id, n.tipo, n.px, n.py, if ent.is_empty() { "—".into() } else { ent.join("  ") }, if sal.is_empty() { "—".into() } else { sal.join("  ") })
        }
        None => "Sin nodo seleccionado".to_string(),
    };
    egui::ScrollArea::vertical().max_height(alto_info).show(ui, |ui| ui.label(txt));
    pulsado
}
