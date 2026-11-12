// Iconos vectoriales dibujados con el Painter de egui (sin depender de fuentes de simbolos): transporte, deshacer/rehacer, herramientas, ojo.
// Estilo plano de trazo fino, dibujado integramente en codigo (no se copia ningun icono, fuente ni logo de terceros); el boton activo se resalta con fondo turquesa.
use egui::{pos2, vec2, Color32, Painter, Pos2, Rect, Response, Sense, Shape, Stroke, StrokeKind, Ui};

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Icono {
    Deshacer,
    Rehacer,
    Inicio,
    Fin,
    Play,
    Pausa,
    Bucle,
    Seleccionar,
    Mover,
    Rotar,
    Escalar,
    Ojo,
    OjoCerrado,
}

const ACENTO: Color32 = Color32::from_rgb(0, 150, 185);

fn arco(c: Pos2, r: f32, a0: f32, a1: f32) -> Vec<Pos2> {
    (0..=24).map(|i| { let a = (a0 + (a1 - a0) * i as f32 / 24.0).to_radians(); c + vec2(a.cos(), -a.sin()) * r }).collect()
}
fn punta(p: &Painter, v: Pos2, dir: egui::Vec2, t: f32, col: Color32) {
    let d = dir.normalized();
    let n = vec2(-d.y, d.x);
    p.add(Shape::convex_polygon(vec![v + d * t, v - d * t * 0.3 + n * t * 0.7, v - d * t * 0.3 - n * t * 0.7], col, Stroke::NONE));
}

pub fn dibujar(p: &Painter, r: Rect, i: Icono, col: Color32) {
    let m = |x: f32, y: f32| r.min + vec2(x * r.width(), y * r.height());
    let u = r.width().min(r.height());
    let st = Stroke::new((u * 0.075).max(1.3), col);
    let t = u * 0.17;
    match i {
        Icono::Play => { p.add(Shape::convex_polygon(vec![m(0.28, 0.15), m(0.28, 0.85), m(0.86, 0.5)], col, Stroke::NONE)); }
        Icono::Pausa => {
            p.rect_filled(Rect::from_min_max(m(0.22, 0.15), m(0.42, 0.85)), 1.0, col);
            p.rect_filled(Rect::from_min_max(m(0.58, 0.15), m(0.78, 0.85)), 1.0, col);
        }
        Icono::Inicio => {
            p.rect_filled(Rect::from_min_max(m(0.14, 0.15), m(0.27, 0.85)), 1.0, col);
            p.add(Shape::convex_polygon(vec![m(0.82, 0.15), m(0.82, 0.85), m(0.32, 0.5)], col, Stroke::NONE));
        }
        Icono::Fin => {
            p.rect_filled(Rect::from_min_max(m(0.73, 0.15), m(0.86, 0.85)), 1.0, col);
            p.add(Shape::convex_polygon(vec![m(0.18, 0.15), m(0.18, 0.85), m(0.68, 0.5)], col, Stroke::NONE));
        }
        Icono::Bucle => {
            p.add(Shape::line(arco(m(0.5, 0.5), u * 0.32, 30.0, 300.0), st));
            punta(p, m(0.5, 0.5) + vec2((30f32).to_radians().cos(), -(30f32).to_radians().sin()) * u * 0.32, vec2(-0.5, -0.9), t, col);
        }
        Icono::Deshacer | Icono::Rehacer => {
            let esp = i == Icono::Rehacer;
            let f = |x: f32| if esp { 1.0 - x } else { x };
            let pts: Vec<Pos2> = arco(m(0.5, 0.58), u * 0.3, 160.0, -60.0).into_iter().map(|q| if esp { pos2(2.0 * r.center().x - q.x, q.y) } else { q }).collect();
            p.add(Shape::line(pts, st));
            let cabeza = m(f(0.17), 0.46);
            punta(p, cabeza, vec2(if esp { 0.5 } else { -0.5 }, -0.9), t * 1.2, col);
        }
        Icono::Seleccionar => {
            let pts = [(0.28, 0.1), (0.28, 0.86), (0.45, 0.69), (0.57, 0.94), (0.68, 0.89), (0.56, 0.64), (0.8, 0.64)];
            p.add(Shape::convex_polygon(pts.iter().map(|&(x, y)| m(x, y)).collect(), col, Stroke::NONE));
        }
        Icono::Mover => {
            p.line_segment([m(0.5, 0.14), m(0.5, 0.86)], st);
            p.line_segment([m(0.14, 0.5), m(0.86, 0.5)], st);
            for (x, y, dx, dy) in [(0.5, 0.06, 0.0, -1.0), (0.5, 0.94, 0.0, 1.0), (0.06, 0.5, -1.0, 0.0), (0.94, 0.5, 1.0, 0.0)] { punta(p, m(x, y), vec2(dx, dy), t, col); }
        }
        Icono::Rotar => {
            p.add(Shape::line(arco(m(0.5, 0.5), u * 0.32, 40.0, 320.0), st));
            let fin = m(0.5, 0.5) + vec2((40f32).to_radians().cos(), -(40f32).to_radians().sin()) * u * 0.32;
            punta(p, fin, vec2(0.7, 0.7), t * 1.2, col);
        }
        Icono::Escalar => {
            p.rect_stroke(Rect::from_min_max(m(0.14, 0.42), m(0.58, 0.86)), 1.0, st, StrokeKind::Inside);
            p.line_segment([m(0.4, 0.6), m(0.82, 0.18)], st);
            punta(p, m(0.88, 0.12), vec2(1.0, -1.0), t * 1.2, col);
        }
        Icono::Ojo | Icono::OjoCerrado => {
            let sup: Vec<Pos2> = (0..=16).map(|k| { let x = k as f32 / 16.0; let y = 0.5 - 0.3 * (1.0 - (2.0 * x - 1.0).powi(2)); m(0.08 + x * 0.84, y) }).collect();
            let inf: Vec<Pos2> = (0..=16).map(|k| { let x = k as f32 / 16.0; let y = 0.5 + 0.3 * (1.0 - (2.0 * x - 1.0).powi(2)); m(0.08 + x * 0.84, y) }).collect();
            if i == Icono::Ojo {
                p.add(Shape::line(sup, st));
                p.add(Shape::line(inf, st));
                p.circle_stroke(m(0.5, 0.5), u * 0.13, st);
                p.circle_filled(m(0.5, 0.5), u * 0.055, col);
            } else {
                p.add(Shape::line(inf, st));
                p.line_segment([m(0.15, 0.2), m(0.85, 0.8)], st);
            }
        }
    }
}

/// boton cuadrado con icono; `activo` = herramienta/estado seleccionado (fondo turquesa); devuelve la respuesta
pub fn boton(ui: &mut Ui, i: Icono, activo: bool, habilitado: bool, lado: f32, tip: &str) -> Response {
    let (r, resp) = ui.allocate_exact_size(vec2(lado, lado), if habilitado { Sense::click() } else { Sense::hover() });
    let p = ui.painter();
    if activo { p.rect_filled(r, 5.0, ACENTO); } else if resp.hovered() && habilitado { p.rect_filled(r, 5.0, Color32::from_white_alpha(22)); }
    let col = if !habilitado { Color32::from_gray(95) } else if activo { Color32::WHITE } else { Color32::from_gray(205) };
    dibujar(p, r.shrink(lado * 0.2), i, col);
    resp.on_hover_text(tip)
}
