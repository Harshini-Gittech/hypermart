import os
import io
import json
import math
import time
import uuid
import struct
import base64
import requests
from flask import Blueprint, request, jsonify, send_from_directory, current_app
from werkzeug.utils import secure_filename
from PIL import Image, ImageEnhance, ImageOps, ImageFilter
from dotenv import load_dotenv, find_dotenv
from db import db_pool

load_dotenv(find_dotenv())

seller_bp = Blueprint("seller_bp", __name__)

BASE_PUBLIC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "public"))
VIEWS_DIR = os.path.join(BASE_PUBLIC, "uploads", "seller_views")
AI_DIR = os.path.join(BASE_PUBLIC, "uploads", "ai_products")
MODELS_DIR = os.path.join(BASE_PUBLIC, "uploads", "models")
os.makedirs(VIEWS_DIR, exist_ok=True)
os.makedirs(AI_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)

CASIO_GLB_FILENAME = "casio_calculator.glb"
CASIO_GLB_PATH = os.path.join(MODELS_DIR, CASIO_GLB_FILENAME)

DEFAULT_GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")

GEMINI_IMAGE_MODELS = [
    "gemini-2.5-flash-image",
    "gemini-2.5-flash-image-preview",
    "gemini-2.0-flash-exp-image-generation",
]


def init_seller_tables():
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS model_url TEXT;")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sellers (
                    id SERIAL PRIMARY KEY,
                    firebase_uid TEXT,
                    email TEXT UNIQUE NOT NULL,
                    mobile TEXT,
                    password_hash TEXT,
                    pan_number TEXT,
                    business_name TEXT,
                    business_address TEXT,
                    bank_account TEXT,
                    ifsc_code TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS seller_product_views (
                    id SERIAL PRIMARY KEY,
                    product_id INTEGER NOT NULL,
                    seller_email TEXT NOT NULL,
                    front_view TEXT,
                    back_view TEXT,
                    left_view TEXT,
                    right_view TEXT,
                    top_view TEXT,
                    bottom_view TEXT,
                    ai_generated_image TEXT,
                    model_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("ALTER TABLE seller_product_views ADD COLUMN IF NOT EXISTS model_url TEXT;")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS order_status_tracking (
                    order_id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'Order Confirmed',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
    finally:
        db_pool.putconn(conn)


def _image_to_base64_jpeg(path: str) -> str:
    img = Image.open(path).convert("RGB")
    img = ImageOps.exif_transpose(img)
    img.thumbnail((768, 768), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _extract_product_cutout(path: str) -> Image.Image:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img).convert("RGBA")
    img.thumbnail((512, 512), Image.Resampling.LANCZOS)

    w, h = img.size
    mx = max(2, int(w * 0.04))
    my = max(2, int(h * 0.04))
    img = img.crop((mx, my, w - mx, h - my))

    px = img.load()
    cw, ch = img.size
    for y in range(ch):
        for x in range(cw):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            min_c = min(r, g, b)
            max_c = max(r, g, b)
            if (min_c > 222 and (max_c - min_c) < 26) or (min_c > 195 and (max_c - min_c) < 20):
                px[x, y] = (24, 27, 32, 0)
    return img


def _cutout_to_jpeg_bytes(cutout: Image.Image, bg_rgb=(24, 27, 32)) -> bytes:
    bg = Image.new("RGB", cutout.size, bg_rgb)
    bg.paste(cutout, (0, 0), cutout)
    buf = io.BytesIO()
    bg.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _sample_silhouette_ring(cutout: Image.Image, n_samples: int = 72, scale_xy: float = 1.0, z_val: float = 0.0):
    alpha = cutout.split()[3]
    bbox = alpha.getbbox()
    if not bbox:
        return [
            (math.cos(2.0 * math.pi * (i / n_samples)) * 0.45 * scale_xy,
             math.sin(2.0 * math.pi * (i / n_samples)) * 0.45 * scale_xy,
             z_val)
            for i in range(n_samples)
        ]

    x0, y0, x1, y1 = bbox
    cx = (x0 + x1) * 0.5
    cy = (y0 + y1) * 0.5
    half_w = max((x1 - x0) * 0.5, 1.0)
    half_h = max((y1 - y0) * 0.5, 1.0)

    aspect = half_w / half_h
    if aspect >= 1.0:
        world_w = 0.62
        world_h = max(0.24, 0.62 / aspect)
    else:
        world_h = 0.62
        world_w = max(0.24, 0.62 * aspect)

    w, h = cutout.size
    px = alpha.load()
    max_rad = math.hypot(half_w, half_h)
    raw_radii = []

    for i in range(n_samples):
        ang = 2.0 * math.pi * (i / n_samples)
        dx = math.cos(ang)
        dy = math.sin(ang)
        hit_r = min(half_w, half_h) * 0.5

        step = 1.5
        while step <= max_rad:
            sx = int(round(cx + dx * step))
            sy = int(round(cy - dy * step))
            if sx < 0 or sx >= w or sy < 0 or sy >= h:
                break
            if px[sx, sy] > 70:
                hit_r = step
            step += 1.5

        max_allowed = math.hypot(dx * half_w, dy * half_h) * 1.05
        raw_radii.append(min(hit_r, max_allowed))

    smoothed = []
    for i in range(n_samples):
        window = [raw_radii[(i + k) % n_samples] for k in range(-2, 3)]
        window_sorted = sorted(window)
        smoothed.append(window_sorted[2])

    pts = []
    for i in range(n_samples):
        ang = 2.0 * math.pi * (i / n_samples)
        dx = math.cos(ang)
        dy = math.sin(ang)
        r_val = smoothed[i]
        wx = dx * (r_val / half_w) * world_w * scale_xy
        wy = dy * (r_val / half_h) * world_h * scale_xy
        pts.append((wx, wy, z_val))

    return pts


def _normalize(v):
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return (v[0] / length, v[1] / length, v[2] / length)


def _fallback_silhouette_glb(view_paths: dict, out_filename: str) -> str:
    front_path = view_paths.get("front")
    front_cutout = _extract_product_cutout(front_path)
    back_path = view_paths.get("back") or front_path
    back_cutout = _extract_product_cutout(back_path)

    n_samples = 72
    hz = 0.08

    ring_specs = [
        (-hz, 0.84, back_cutout),
        (-hz * 0.65, 0.96, back_cutout),
        (0.0, 1.0, front_cutout),
        (hz * 0.65, 0.96, front_cutout),
        (hz, 0.84, front_cutout),
    ]
    rings = [
        _sample_silhouette_ring(cut, n_samples=n_samples, scale_xy=sc, z_val=zv)
        for zv, sc, cut in ring_specs
    ]

    bin_data = bytearray()
    buffer_views = []
    accessors = []
    images = []
    textures = []
    materials = []
    primitives = []

    def append_bin(raw_bytes: bytes, target=None) -> int:
        while len(bin_data) % 4 != 0:
            bin_data.append(0)
        offset = len(bin_data)
        bin_data.extend(raw_bytes)
        bv = {"buffer": 0, "byteOffset": offset, "byteLength": len(raw_bytes)}
        if target is not None:
            bv["target"] = target
        buffer_views.append(bv)
        return len(buffer_views) - 1

    def add_primitive(verts_list, norms_list, uvs_list, tris_list, mat_idx):
        pos_bytes = b"".join(struct.pack("<3f", *v) for v in verts_list)
        pos_bv = append_bin(pos_bytes, target=34962)
        min_v = [min(v[i] for v in verts_list) for i in range(3)]
        max_v = [max(v[i] for v in verts_list) for i in range(3)]
        accessors.append({
            "bufferView": pos_bv, "componentType": 5126, "count": len(verts_list),
            "type": "VEC3", "min": min_v, "max": max_v
        })
        pos_acc = len(accessors) - 1

        norm_bytes = b"".join(struct.pack("<3f", *n) for n in norms_list)
        norm_bv = append_bin(norm_bytes, target=34962)
        accessors.append({
            "bufferView": norm_bv, "componentType": 5126, "count": len(norms_list),
            "type": "VEC3"
        })
        norm_acc = len(accessors) - 1

        uv_bytes = b"".join(struct.pack("<2f", *u) for u in uvs_list)
        uv_bv = append_bin(uv_bytes, target=34962)
        accessors.append({
            "bufferView": uv_bv, "componentType": 5126, "count": len(uvs_list),
            "type": "VEC2"
        })
        uv_acc = len(accessors) - 1

        idx_bytes = b"".join(struct.pack("<3I", *t) for t in tris_list)
        idx_bv = append_bin(idx_bytes, target=34963)
        accessors.append({
            "bufferView": idx_bv, "componentType": 5125, "count": len(tris_list) * 3,
            "type": "SCALAR"
        })
        idx_acc = len(accessors) - 1

        primitives.append({
            "attributes": {"POSITION": pos_acc, "NORMAL": norm_acc, "TEXCOORD_0": uv_acc},
            "indices": idx_acc,
            "material": mat_idx
        })

    for idx, (cut, rough, metal, bg_col) in enumerate([
        (front_cutout, 0.34, 0.12, (24, 27, 32)),
        (back_cutout, 0.38, 0.12, (24, 27, 32)),
        (front_cutout, 0.35, 0.20, (24, 27, 32)),
    ]):
        img_bytes = _cutout_to_jpeg_bytes(cut, bg_rgb=bg_col)
        img_bv = append_bin(img_bytes)
        images.append({"bufferView": img_bv, "mimeType": "image/jpeg"})
        textures.append({"source": idx})
        materials.append({
            "name": f"mat_{idx}",
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": idx},
                "metallicFactor": metal,
                "roughnessFactor": rough
            }
        })

    max_x = max(abs(p[0]) for r in rings for p in r) or 0.5
    max_y = max(abs(p[1]) for r in rings for p in r) or 0.5

    rim_verts, rim_norms, rim_uvs, rim_tris = [], [], [], []
    num_slices = len(rings)
    for s_idx, ring in enumerate(rings):
        v_coord = 1.0 - (s_idx / (num_slices - 1))
        for i, (x, y, z) in enumerate(ring):
            u_coord = i / n_samples
            n = _normalize((x / max_x, y / max_y, (z / hz) * 0.35))
            rim_verts.append((x, y, z))
            rim_norms.append(n)
            rim_uvs.append((u_coord, v_coord))

    for s_idx in range(num_slices - 1):
        r0 = s_idx * n_samples
        r1 = (s_idx + 1) * n_samples
        for i in range(n_samples):
            ni = (i + 1) % n_samples
            a, b, c, d = r0 + i, r0 + ni, r1 + ni, r1 + i
            rim_tris.append((a, b, c))
            rim_tris.append((a, c, d))

    add_primitive(rim_verts, rim_norms, rim_uvs, rim_tris, 2)

    for ring_idx, z_dir, mat_i in [(-1, 1.0, 0), (0, -1.0, 1)]:
        ring = rings[ring_idx]
        cz = ring[0][2]
        cap_verts = [(0.0, 0.0, cz)]
        cap_norms = [(0.0, 0.0, z_dir)]
        cap_uvs = [(0.5, 0.5)]

        for x, y, z in ring:
            u = 0.5 + (x / (2.0 * max_x)) * 0.88
            v = 0.5 - (y / (2.0 * max_y)) * 0.88
            cap_verts.append((x, y, z))
            cap_norms.append((0.0, 0.0, z_dir))
            cap_uvs.append((max(0.0, min(1.0, u)), max(0.0, min(1.0, v))))

        cap_tris = []
        for i in range(1, n_samples + 1):
            ni = 1 if i == n_samples else i + 1
            if z_dir > 0:
                cap_tris.append((0, i, ni))
            else:
                cap_tris.append((0, ni, i))

        add_primitive(cap_verts, cap_norms, cap_uvs, cap_tris, mat_i)

    while len(bin_data) % 4 != 0:
        bin_data.append(0)

    gltf = {
        "asset": {"version": "2.0", "generator": "HyperMart Silhouette Fallback"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "ProductMesh"}],
        "meshes": [{"primitives": primitives}],
        "materials": materials,
        "textures": textures,
        "images": images,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(bin_data)}]
    }

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    while len(json_bytes) % 4 != 0:
        json_bytes += b" "

    total_length = 12 + 8 + len(json_bytes) + 8 + len(bin_data)
    glb = bytearray()
    glb.extend(struct.pack("<4sII", b"glTF", 2, total_length))
    glb.extend(struct.pack("<I4s", len(json_bytes), b"JSON"))
    glb.extend(json_bytes)
    glb.extend(struct.pack("<I4s", len(bin_data), b"BIN\x00"))
    glb.extend(bin_data)

    out_path = os.path.join(MODELS_DIR, out_filename)
    with open(out_path, "wb") as f:
        f.write(glb)

    return f"/uploads/models/{out_filename}"


def _upload_view_to_tripo(image_path: str, base_url: str, headers: dict):
    with open(image_path, "rb") as f:
        resp = requests.post(
            f"{base_url}/files",
            headers=headers,
            files={"file": (os.path.basename(image_path), f, "image/jpeg")},
            timeout=30
        )
    if not resp.ok:
        raise RuntimeError(f"Tripo upload failed at {base_url}/files ({resp.status_code}): {resp.text[:220]}")
    payload = resp.json()
    data = payload.get("data") or payload
    token = data.get("file_token") or data.get("image_token") or data.get("token")
    if not token:
        raise RuntimeError(f"Tripo upload returned no file_token: {payload}")
    return token


def _extract_glb_url_from_task(task_data: dict):
    output = task_data.get("output") or {}
    for key in ("model_url", "glb_url", "pbr_model", "base_model", "model"):
        val = output.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
        if isinstance(val, dict):
            for sub in ("url", "glb_url", "model_url"):
                if isinstance(val.get(sub), str) and val[sub].startswith("http"):
                    return val[sub]

    result = task_data.get("result") or {}
    for key in ("model", "pbr_model", "model_url", "glb_url"):
        val = result.get(key)
        if isinstance(val, str) and val.startswith("http"):
            return val
        if isinstance(val, dict) and isinstance(val.get("url"), str):
            return val["url"]

    return None


def _run_tripo_on_base_url(base_url: str, tripo_key: str, view_paths: dict, out_filename: str):
    auth_headers = {"Authorization": f"Bearer {tripo_key}"}
    view_order = ["front", "left", "back", "right"]
    inputs = []
    for v_key in view_order:
        p = view_paths.get(v_key)
        if p and os.path.exists(p):
            token = _upload_view_to_tripo(p, base_url, auth_headers)
            inputs.append({v_key: {"file_token": token}})

    if len(inputs) < 2 or not any("front" in item for item in inputs):
        raise RuntimeError("Tripo multiview requires 'front' and at least one other view (left/back/right).")

    create_payload = {
        "inputs": inputs,
        "model": "v3.1-20260211",
        "texture": True,
        "pbr": True,
        "texture_quality": "standard",
        "texture_alignment": "original_image"
    }
    json_headers = {**auth_headers, "Content-Type": "application/json"}
    create_resp = requests.post(
        f"{base_url}/generation/multiview-to-model",
        headers=json_headers,
        json=create_payload,
        timeout=30
    )
    if not create_resp.ok:
        raise RuntimeError(f"Tripo task error ({create_resp.status_code}): {create_resp.text[:220]}")

    create_json = create_resp.json()
    task_id = (create_json.get("data") or create_json).get("task_id")
    if not task_id:
        raise RuntimeError(f"Tripo task_id missing: {create_json}")

    print(f"[Tripo 3D] Started task {task_id} on {base_url}; polling...")
    glb_url = None
    for _ in range(50):
        time.sleep(3)
        poll_resp = requests.get(f"{base_url}/tasks/{task_id}", headers=auth_headers, timeout=20)
        if not poll_resp.ok:
            continue
        poll_json = poll_resp.json()
        t_data = poll_json.get("data") or poll_json
        status = str(t_data.get("status") or "").lower()
        if status in ("success", "completed", "succeeded"):
            glb_url = _extract_glb_url_from_task(t_data)
            break
        if status in ("failed", "error", "cancelled", "canceled"):
            raise RuntimeError(f"Tripo task {task_id} ended with status: {status} ({t_data})")

    if not glb_url:
        raise RuntimeError(f"Tripo task {task_id} timed out or returned no GLB URL.")

    dl_resp = requests.get(glb_url, timeout=90)
    if not dl_resp.ok or len(dl_resp.content) < 64:
        raise RuntimeError(f"Failed to download Tripo GLB from {glb_url}")

    out_path = os.path.join(MODELS_DIR, out_filename)
    with open(out_path, "wb") as f:
        f.write(dl_resp.content)

    print(f"[Tripo 3D] Saved {out_filename} from task {task_id}")
    return f"/uploads/models/{out_filename}"


def _resolve_preset_glb_path(product_name: str, category: str) -> str:
    combined = f"{product_name or ''} {category or ''}".lower()
    if ("casio" in combined or "calculator" in combined) and os.path.isfile(CASIO_GLB_PATH):
        return CASIO_GLB_PATH
    return None


def generate_3d_glb_from_views(
    view_paths: dict,
    out_filename: str,
    custom_glb_path: str = None,
    product_name: str = "",
    category: str = ""
) -> str:
    chosen_glb = custom_glb_path or _resolve_preset_glb_path(product_name, category)
    if chosen_glb and os.path.isfile(chosen_glb):
        if os.path.abspath(chosen_glb) == os.path.abspath(CASIO_GLB_PATH):
            return f"/uploads/models/{CASIO_GLB_FILENAME}"
        out_path = os.path.join(MODELS_DIR, out_filename)
        with open(chosen_glb, "rb") as src_f, open(out_path, "wb") as dst_f:
            dst_f.write(src_f.read())
        return f"/uploads/models/{out_filename}"

    tripo_key = (os.getenv("TRIPO_API_KEY") or "").strip()
    if not tripo_key:
        print("[Tripo 3D] No TRIPO_API_KEY found; using silhouette fallback.")
        return _fallback_silhouette_glb(view_paths, out_filename)

    configured_url = (os.getenv("TRIPO_BASE_URL") or "").strip().rstrip("/")
    candidate_urls = []
    for u in [configured_url, "https://openapi.tripo3d.ai/v3", "https://openapi.tripo3d.com/v3"]:
        if u and u not in candidate_urls:
            candidate_urls.append(u)

    last_err = None
    for base_url in candidate_urls:
        try:
            return _run_tripo_on_base_url(base_url, tripo_key, view_paths, out_filename)
        except Exception as e:
            last_err = e
            print(f"[Tripo 3D Attempt Failed @ {base_url}] {e}")

    print(f"[Tripo 3D Fallback] All endpoints failed; last error: {last_err}")
    return _fallback_silhouette_glb(view_paths, out_filename)


def generate_ai_studio_image(view_paths: dict, product_name: str, category: str, out_filename: str):
    out_path = os.path.join(AI_DIR, out_filename)
    gemini_key = (os.getenv("GEMINI_API_KEY") or DEFAULT_GEMINI_KEY).strip()
    last_error = "No GEMINI_API_KEY configured."

    if gemini_key:
        prompt = (
            f"Generate a professional, ultra-sharp commercial e-commerce studio product photograph "
            f"of this exact '{product_name}' ({category}) using the uploaded reference photos. "
            f"Place the product centered at a clean 3/4 hero angle on a pure white studio background "
            f"with a soft natural contact shadow underneath. Remove all text labels, hands, borders, "
            f"and background clutter. Keep the exact product shape, color, and details faithful."
        )

        parts = [{"text": prompt}]
        for key in ["front", "left", "right", "back", "top"]:
            p = view_paths.get(key)
            if p and os.path.exists(p):
                parts.append({
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": _image_to_base64_jpeg(p)
                    }
                })

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}
        }
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": gemini_key
        }

        for model_name in GEMINI_IMAGE_MODELS:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
                resp = requests.post(url, json=payload, headers=headers, timeout=45)
                if resp.ok:
                    body = resp.json()
                    for cand in (body.get("candidates") or []):
                        for part in (cand.get("content", {}).get("parts") or []):
                            inline = part.get("inlineData") or part.get("inline_data")
                            if inline and inline.get("data"):
                                img_bytes = base64.b64decode(inline["data"])
                                gen_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                                gen_img.save(out_path, format="JPEG", quality=94)
                                return f"/uploads/ai_products/{out_filename}", f"Gemini AI ({model_name})", ""
                    last_error = f"{model_name} returned no image data."
                else:
                    last_error = f"{model_name} HTTP {resp.status_code}"
            except Exception as e:
                last_error = f"{model_name} error: {e}"

    front_path = view_paths.get("front")
    img = Image.open(front_path).convert("RGB")
    img = ImageOps.exif_transpose(img)
    img = ImageEnhance.Contrast(img).enhance(1.14)
    img = ImageEnhance.Color(img).enhance(1.16)
    img = ImageEnhance.Sharpness(img).enhance(1.30)
    img = ImageEnhance.Brightness(img).enhance(1.06)

    canvas = Image.new("RGBA", (900, 900), (255, 255, 255, 255))
    img.thumbnail((720, 720), Image.Resampling.LANCZOS)

    shadow = Image.new("RGBA", (img.width + 40, img.height + 40), (0, 0, 0, 0))
    shadow_box = Image.new("RGBA", (img.width, img.height), (15, 23, 42, 42))
    shadow.paste(shadow_box, (20, 26))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))

    canvas.alpha_composite(shadow, ((900 - shadow.width) // 2, (900 - shadow.height) // 2))
    canvas.paste(img, ((900 - img.width) // 2, (900 - img.height) // 2))
    canvas.convert("RGB").save(out_path, format="JPEG", quality=94)
    return f"/uploads/ai_products/{out_filename}", "Studio Image", last_error


def index_product_in_opensearch(doc: dict):
    os_uri = os.getenv("OPENSEARCH_URI", "").strip()
    if not os_uri:
        return
    try:
        url = f"{os_uri.rstrip('/')}/products/_doc/{doc['id']}?refresh=true"
        requests.put(url, json=doc, timeout=6, verify=False)
    except Exception as e:
        print(f"[OpenSearch Sync Warning] {e}")


@seller_bp.route("/uploads/models/<path:filename>")
def serve_model_glb(filename):
    safe_name = os.path.basename(filename)
    model_path = os.path.join(MODELS_DIR, safe_name)
    if not os.path.isfile(model_path):
        return jsonify({"success": False, "message": "3D model not found"}), 404
    return send_from_directory(MODELS_DIR, safe_name, mimetype="model/gltf-binary")


@seller_bp.route("/uploads/<path:subpath>")
def serve_uploads(subpath):
    return send_from_directory(os.path.join(BASE_PUBLIC, "uploads"), subpath)


@seller_bp.route("/api/seller/register", methods=["POST"])
def register_seller():
    init_seller_tables()
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"success": False, "message": "Email is required"}), 400

    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO sellers (
                    firebase_uid, email, mobile, password_hash,
                    pan_number, business_name, business_address, bank_account, ifsc_code
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (email) DO UPDATE SET
                    mobile = EXCLUDED.mobile,
                    pan_number = EXCLUDED.pan_number,
                    business_name = EXCLUDED.business_name,
                    business_address = EXCLUDED.business_address,
                    bank_account = EXCLUDED.bank_account,
                    ifsc_code = EXCLUDED.ifsc_code
                RETURNING id, email, business_name;
            """, (
                data.get("firebase_uid", ""),
                email,
                data.get("mobile", ""),
                data.get("password", ""),
                data.get("pan_number", ""),
                data.get("business_name", ""),
                data.get("business_address", ""),
                data.get("bank_account", ""),
                data.get("ifsc_code", ""),
            ))
            row = cur.fetchone()
            conn.commit()
            return jsonify({
                "success": True,
                "seller": {"id": row[0], "email": row[1], "business_name": row[2]}
            })
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db_pool.putconn(conn)


@seller_bp.route("/api/seller/generate-preview", methods=["POST"])
def generate_preview():
    name = (request.form.get("name") or "").strip()
    category = (request.form.get("category") or "Accessories").strip()
    existing_model_url = (request.form.get("model_url") or "").strip()

    if not name or "front" not in request.files:
        return jsonify({"success": False, "message": "Product name and Front View photo are required."}), 400

    batch_id = uuid.uuid4().hex[:10]
    view_keys = ["front", "back", "left", "right", "top", "bottom"]
    saved_urls = {}
    disk_paths = {}

    for key in view_keys:
        file = request.files.get(key)
        if file and file.filename:
            ext = os.path.splitext(secure_filename(file.filename))[1] or ".jpg"
            fname = f"{batch_id}_{key}{ext}"
            fpath = os.path.join(VIEWS_DIR, fname)
            file.save(fpath)
            saved_urls[key] = f"/uploads/seller_views/{fname}"
            disk_paths[key] = fpath
        else:
            saved_urls[key] = None
            disk_paths[key] = None

    custom_glb_path = None
    model_file = request.files.get("model_file")
    if model_file and model_file.filename:
        custom_glb_path = os.path.join(MODELS_DIR, f"{batch_id}_uploaded_raw.glb")
        model_file.save(custom_glb_path)
    elif existing_model_url.startswith("/uploads/models/"):
        candidate = os.path.join(MODELS_DIR, os.path.basename(existing_model_url))
        if os.path.isfile(candidate):
            custom_glb_path = candidate

    ai_image_url, ai_engine, ai_note = generate_ai_studio_image(
        disk_paths, name, category, f"{batch_id}_ai_studio.jpg"
    )
    model_url = generate_3d_glb_from_views(
        disk_paths,
        f"{batch_id}_model.glb",
        custom_glb_path=custom_glb_path,
        product_name=name,
        category=category
    )

    if custom_glb_path and custom_glb_path.endswith("_uploaded_raw.glb") and os.path.exists(custom_glb_path):
        try:
            os.remove(custom_glb_path)
        except OSError:
            pass

    return jsonify({
        "success": True,
        "batch_id": batch_id,
        "ai_image_url": ai_image_url,
        "model_url": model_url,
        "ai_engine": ai_engine,
        "ai_note": ai_note,
        "saved_views": saved_urls
    })


@seller_bp.route("/api/seller/submit-listing", methods=["POST"])
def submit_listing():
    init_seller_tables()
    data = request.get_json(force=True)

    name = (data.get("name") or "").strip()
    category = (data.get("category") or "Accessories").strip()
    city = (data.get("city") or "Bengaluru").strip()
    price = float(data.get("price") or 999)
    stock = int(data.get("stock") or 10)
    seller_email = (data.get("seller_email") or "seller@hypermart.in").strip().lower()
    ai_image_url = data.get("ai_image_url")
    model_url = (data.get("model_url") or "").strip()
    saved_views = data.get("saved_views") or {}

    if not name or not ai_image_url:
        return jsonify({"success": False, "message": "Generate the listing image & 3D model before submitting."}), 400

    preset_glb = _resolve_preset_glb_path(name, category)
    if not model_url and preset_glb:
        model_url = f"/uploads/models/{CASIO_GLB_FILENAME}"

    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT setval(
                    pg_get_serial_sequence('products', 'id'),
                    COALESCE((SELECT MAX(id) FROM products), 1),
                    true
                );
            """)

            cur.execute("""
                INSERT INTO products (name, category, price, city, inventory_count, image_url, model_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (name, category, price, city, stock, ai_image_url, model_url))
            product_id = cur.fetchone()[0]

            cur.execute("""
                INSERT INTO seller_product_views (
                    product_id, seller_email, front_view, back_view,
                    left_view, right_view, top_view, bottom_view, ai_generated_image, model_url
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
            """, (
                product_id, seller_email,
                saved_views.get("front"), saved_views.get("back"),
                saved_views.get("left"), saved_views.get("right"),
                saved_views.get("top"), saved_views.get("bottom"),
                ai_image_url, model_url
            ))
            view_record_id = cur.fetchone()[0]
            conn.commit()

        index_product_in_opensearch({
            "id": product_id,
            "name": name,
            "category": category,
            "price": price,
            "city": city,
            "inventory_count": stock,
            "image_url": ai_image_url,
            "model_url": model_url,
            "tags": f"{name} {category} {city}"
        })

        return jsonify({
            "success": True,
            "product_id": product_id,
            "view_record_id": view_record_id,
            "ai_image_url": ai_image_url,
            "model_url": model_url
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db_pool.putconn(conn)


@seller_bp.route("/api/seller/admin/report", methods=["GET"])
def seller_admin_report():
    init_seller_tables()
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT p.id, p.name, p.category, p.price, p.inventory_count, p.image_url, p.city, p.model_url
                FROM products p
                ORDER BY p.id DESC;
            """)
            products = [{
                "id": r[0], "name": r[1], "category": r[2],
                "price": float(r[3]), "stock": int(r[4]),
                "image_url": r[5], "city": r[6] or "Bengaluru",
                "model_url": r[7]
            } for r in cur.fetchall()]

            cur.execute("""
                SELECT o.id, o.product_id, p.name, p.price, o.quantity, o.order_date,
                       COALESCE(s.status, 'Order Confirmed') AS status, p.image_url
                FROM orders o
                JOIN products p ON p.id = o.product_id
                LEFT JOIN order_status_tracking s ON s.order_id = o.id
                ORDER BY o.order_date DESC;
            """)
            orders = []
            total_revenue = 0.0
            total_units = 0
            for r in cur.fetchall():
                line_total = float(r[3]) * int(r[4])
                total_revenue += line_total
                total_units += int(r[4])
                orders.append({
                    "id": r[0],
                    "product_id": r[1],
                    "product_name": r[2],
                    "price": float(r[3]),
                    "quantity": int(r[4]),
                    "total": line_total,
                    "order_date": r[5].isoformat() if r[5] else "",
                    "status": r[6],
                    "image_url": r[7]
                })

            return jsonify({
                "success": True,
                "summary": {
                    "total_revenue": total_revenue,
                    "total_orders": len(orders),
                    "total_units_sold": total_units,
                    "total_products": len(products)
                },
                "products": products,
                "orders": orders
            })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db_pool.putconn(conn)


@seller_bp.route("/api/seller/admin/order-status", methods=["POST"])
def update_order_status():
    init_seller_tables()
    data = request.get_json(force=True)
    order_id = data.get("order_id")
    new_status = (data.get("status") or "").strip()

    if not order_id or not new_status:
        return jsonify({"success": False, "message": "order_id and status are required"}), 400

    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO order_status_tracking (order_id, status, updated_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (order_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    updated_at = CURRENT_TIMESTAMP;
            """, (int(order_id), new_status))

            cur.execute("""
                SELECT p.name FROM orders o
                JOIN products p ON p.id = o.product_id
                WHERE o.id = %s;
            """, (int(order_id),))
            row = cur.fetchone()
            product_name = row[0] if row else f"Order #{order_id}"
            conn.commit()

        sio = current_app.config.get("SOCKETIO")
        if sio:
            sio.emit("order_status_updated", {
                "orderId": int(order_id),
                "productName": product_name,
                "status": new_status
            })

        return jsonify({
            "success": True,
            "order_id": int(order_id),
            "product_name": product_name,
            "status": new_status
        })
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        db_pool.putconn(conn)


@seller_bp.route("/api/orders/statuses", methods=["GET"])
def get_order_statuses():
    init_seller_tables()
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT order_id, status FROM order_status_tracking;")
            return jsonify({str(r[0]): r[1] for r in cur.fetchall()})
    finally:
        db_pool.putconn(conn)