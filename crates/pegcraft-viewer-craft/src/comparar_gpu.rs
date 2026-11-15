// Comparación de píxeles GPU (vello) vs CPU (tiny-skia, calidad Completa) sobre fotogramas ya horneados.
// Uso: pegcraft-viewer-craft ESCENA1[;ESCENA2...] --comparar-gpu SALIDA [--cuadros 9,59,109]
//   ESCENA = carpeta horneada (f0001\escena.json ...). Escribe SALIDA\comparacion.json y tres láminas PNG:
//   lamina_<escena>.png (por escena: filas = fotogramas, columnas = CPU | GPU | diferencia x8) y detalle.png (recorte 1:1 ampliado x4 de la zona más distinta).
// Cifras por fotograma (fondo gris 128, como se ve en el visor):
//   media_px = diferencia absoluta media por canal RGB sobre TODOS los píxeles (0-255); media_distintos = ídem solo sobre los píxeles con alguna diferencia;
//   max = diferencia máxima de un canal; pct_gt16 / pct_gt64 = % de píxeles cuyo canal más distinto supera 16 / 64.
// Con fondo transparente: iou_alfa = |A∩B| / |A∪B| con A = alfa CPU >= 128, B = alfa GPU >= 128; iou_alfa_suave = Σmin(aC,aG) / Σmax(aC,aG).
use crate::render::{self, Cache, Calidad, Estado};
use crate::render_gpu::Gpu;
use std::path::{Path, PathBuf};
use tiny_skia::Pixmap;

struct Cifras {
    media_px: f64,
    media_distintos: f64,
    max: u8,
    pct_gt16: f64,
    pct_gt64: f64,
    iou_alfa: f64,
    iou_alfa_suave: f64,
}

fn diferencia(a: &Pixmap, b: &Pixmap) -> (Pixmap, f64, f64, u8, f64, f64, Vec<u32>, usize) {
    let (w, h) = (a.width() as usize, a.height() as usize);
    let (da, db) = (a.data(), b.data());
    let mut dif = Pixmap::new(w as u32, h as u32).unwrap();
    let dd = dif.data_mut();
    let (mut suma, mut dist, mut n_dist, mut mx, mut g16, mut g64) = (0u64, 0u64, 0u64, 0u8, 0u64, 0u64);
    // suma de diferencias por bloque de 80x80 (para elegir el recorte de detalle)
    let bw = w.div_ceil(80);
    let mut bloques = vec![0u32; bw * h.div_ceil(80)];
    for i in 0..w * h {
        let (mut s, mut m) = (0u32, 0u8);
        for c in 0..3 {
            let d = (da[i * 4 + c] as i32 - db[i * 4 + c] as i32).unsigned_abs() as u8;
            s += d as u32;
            m = m.max(d);
        }
        suma += s as u64;
        if m > 0 {
            dist += s as u64;
            n_dist += 1;
        }
        mx = mx.max(m);
        if m > 16 { g16 += 1; }
        if m > 64 { g64 += 1; }
        let r = (m as u32 * 8).min(255) as u8;
        dd[i * 4] = r;
        dd[i * 4 + 3] = 255;
        bloques[(i / w / 80) * bw + (i % w) / 80] += s;
    }
    let np = (w * h) as f64;
    (dif, suma as f64 / (np * 3.0), if n_dist > 0 { dist as f64 / (n_dist as f64 * 3.0) } else { 0.0 }, mx, g16 as f64 * 100.0 / np, g64 as f64 * 100.0 / np, bloques, bw)
}

fn iou_alfa(a: &Pixmap, b: &Pixmap) -> (f64, f64) {
    let (da, db) = (a.data(), b.data());
    let (mut inter, mut uni, mut smin, mut smax) = (0u64, 0u64, 0u64, 0u64);
    for i in 0..(a.width() * a.height()) as usize {
        let (x, y) = (da[i * 4 + 3], db[i * 4 + 3]);
        let (ba, bb) = (x >= 128, y >= 128);
        if ba && bb { inter += 1; }
        if ba || bb { uni += 1; }
        smin += x.min(y) as u64;
        smax += x.max(y) as u64;
    }
    (if uni > 0 { inter as f64 / uni as f64 } else { 1.0 }, if smax > 0 { smin as f64 / smax as f64 } else { 1.0 })
}

fn reducir2(p: &Pixmap) -> Pixmap {
    let (w, h) = (p.width() as usize / 2, p.height() as usize / 2);
    let mut o = Pixmap::new(w as u32, h as u32).unwrap();
    let (s, d) = (p.data(), o.data_mut());
    let sw = p.width() as usize;
    for y in 0..h {
        for x in 0..w {
            for c in 0..4 {
                let t = s[((2 * y) * sw + 2 * x) * 4 + c] as u32 + s[((2 * y) * sw + 2 * x + 1) * 4 + c] as u32 + s[((2 * y + 1) * sw + 2 * x) * 4 + c] as u32 + s[((2 * y + 1) * sw + 2 * x + 1) * 4 + c] as u32;
                d[(y * w + x) * 4 + c] = ((t + 2) / 4) as u8;
            }
        }
    }
    o
}

fn pegar(dst: &mut Pixmap, src: &Pixmap, ox: usize, oy: usize) {
    let dw = dst.width() as usize;
    let sw = src.width() as usize;
    let (s, d) = (src.data(), dst.data_mut());
    for y in 0..src.height() as usize {
        let (a, b) = ((y * sw) * 4, (y * sw + sw) * 4);
        let o = ((oy + y) * dw + ox) * 4;
        d[o..o + (b - a)].copy_from_slice(&s[a..b]);
    }
}

fn recorte(p: &Pixmap, x0: usize, y0: usize, tam: usize, zoom: usize) -> Pixmap {
    let mut o = Pixmap::new((tam * zoom) as u32, (tam * zoom) as u32).unwrap();
    let (w, h) = (p.width() as usize, p.height() as usize);
    let (s, d) = (p.data(), o.data_mut());
    for y in 0..tam * zoom {
        for x in 0..tam * zoom {
            let (sx, sy) = ((x0 + x / zoom).min(w - 1), (y0 + y / zoom).min(h - 1));
            d[(y * tam * zoom + x) * 4..(y * tam * zoom + x) * 4 + 4].copy_from_slice(&s[(sy * w + sx) * 4..(sy * w + sx) * 4 + 4]);
        }
    }
    o
}

pub fn comparar(rutas: &Path, salida: &Path, cuadros: &[usize]) {
    std::fs::create_dir_all(salida).expect("crear salida");
    let mut gpu = Gpu::nuevo().unwrap_or_else(|e| { eprintln!("GPU no disponible: {e}"); std::process::exit(1) });
    println!("GPU: {} (init {:.0} ms)", gpu.adaptador, gpu.init_ms);
    let st = Estado::default();
    let mut resumen = vec![];
    let mut detalles: Vec<(String, Pixmap, Pixmap, Pixmap)> = vec![];
    for esc in rutas.to_string_lossy().split(';').filter(|s| !s.is_empty()) {
        let carpeta = PathBuf::from(esc);
        let nombre = carpeta.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or("escena".into());
        let archivos = crate::descubrir(&carpeta);
        let n = archivos.len();
        let idx: Vec<usize> = if cuadros.is_empty() { vec![n / 10, n / 2, n - 1 - n / 10] } else { cuadros.iter().map(|&c| c.min(n - 1)).collect() };
        let mut cache = Cache::default();
        gpu.vaciar_cache();
        let mut filas = vec![];
        let mut lamina: Vec<(Pixmap, Pixmap, Pixmap)> = vec![];
        let mut peor: Option<(f64, usize, Vec<u32>, usize, Pixmap, Pixmap, Pixmap)> = None;
        for &i in &idx {
            let e = render::cargar(&archivos[i]).expect("cargar escena");
            let cpu = render::render_fondo(&e, &mut cache, &st, Calidad::Completa, true);
            let g = gpu.render(&e, &st, Calidad::Completa, true).expect("render GPU");
            let (dif, media, media_d, mx, g16, g64, bloques, bw) = diferencia(&cpu, &g);
            let cpu_t = render::render_fondo(&e, &mut cache, &st, Calidad::Completa, false);
            let g_t = gpu.render(&e, &st, Calidad::Completa, false).expect("render GPU");
            let (iou, iou_s) = iou_alfa(&cpu_t, &g_t);
            let c = Cifras { media_px: media, media_distintos: media_d, max: mx, pct_gt16: g16, pct_gt64: g64, iou_alfa: iou, iou_alfa_suave: iou_s };
            println!(
                "{nombre} f{:04} (idx {i}): media {:.3} | media en distintos {:.2} | max {} | >16: {:.3}% | >64: {:.3}% | IoU alfa {:.5} (suave {:.5})",
                e.fotograma, c.media_px, c.media_distintos, c.max, c.pct_gt16, c.pct_gt64, c.iou_alfa, c.iou_alfa_suave
            );
            filas.push(serde_json::json!({
                "indice": i, "fotograma": e.fotograma, "piezas": e.piezas.len(), "media_px": c.media_px, "media_distintos": c.media_distintos, "max": c.max,
                "pct_gt16": c.pct_gt16, "pct_gt64": c.pct_gt64, "iou_alfa": c.iou_alfa, "iou_alfa_suave": c.iou_alfa_suave,
            }));
            if peor.as_ref().map(|p| media > p.0).unwrap_or(true) {
                peor = Some((media, i, bloques, bw, cpu.clone(), g.clone(), dif.clone()));
            }
            lamina.push((reducir2(&cpu), reducir2(&g), reducir2(&dif)));
        }
        // lámina de la escena: filas = fotogramas; columnas = CPU | GPU | diferencia x8
        let (pw, ph) = (lamina[0].0.width() as usize, lamina[0].0.height() as usize);
        let mut big = Pixmap::new((pw * 3 + 8) as u32, (ph * lamina.len() + 4 * (lamina.len() - 1)) as u32).unwrap();
        big.fill(tiny_skia::Color::from_rgba8(20, 20, 20, 255));
        for (r, (a, b, d)) in lamina.iter().enumerate() {
            let y = r * (ph + 4);
            pegar(&mut big, a, 0, y);
            pegar(&mut big, b, pw + 4, y);
            pegar(&mut big, d, 2 * (pw + 4), y);
        }
        let png = salida.join(format!("lamina_{nombre}.png"));
        big.save_png(&png).expect("png");
        println!("-> {}", png.display());
        if let Some((_, i, bloques, bw, cpu, g, dif)) = peor {
            let (mut mejor, mut bx, mut by) = (0u32, 0usize, 0usize);
            for (k, s) in bloques.iter().enumerate() {
                if *s > mejor { mejor = *s; bx = k % bw; by = k / bw; }
            }
            let (x0, y0) = ((bx * 80).saturating_sub(40).min(cpu.width() as usize - 160), (by * 80).saturating_sub(40).min(cpu.height() as usize - 160));
            detalles.push((format!("{nombre} idx {i}"), recorte(&cpu, x0, y0, 160, 4), recorte(&g, x0, y0, 160, 4), recorte(&dif, x0, y0, 160, 4)));
        }
        resumen.push(serde_json::json!({ "escena": nombre, "carpeta": esc, "calidad": "Completa", "adaptador": gpu.adaptador, "cuadros": filas }));
    }
    if !detalles.is_empty() {
        let (pw, ph) = (detalles[0].1.width() as usize, detalles[0].1.height() as usize);
        let mut big = Pixmap::new((pw * 3 + 8) as u32, (ph * detalles.len() + 4 * (detalles.len() - 1)) as u32).unwrap();
        big.fill(tiny_skia::Color::from_rgba8(20, 20, 20, 255));
        for (r, (_, a, b, d)) in detalles.iter().enumerate() {
            let y = r * (ph + 4);
            pegar(&mut big, a, 0, y);
            pegar(&mut big, b, pw + 4, y);
            pegar(&mut big, d, 2 * (pw + 4), y);
        }
        let png = salida.join("detalle.png");
        big.save_png(&png).expect("png");
        println!("-> {} (filas: {})", png.display(), detalles.iter().map(|d| d.0.as_str()).collect::<Vec<_>>().join(" | "));
    }
    let j = salida.join("comparacion.json");
    std::fs::write(&j, serde_json::to_string_pretty(&resumen).unwrap()).expect("json");
    println!("-> {}", j.display());
}
