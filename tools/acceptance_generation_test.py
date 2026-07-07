from __future__ import annotations

import argparse
import base64
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"
ASSETS = LOGS / "acceptance-assets"


def data_url(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def font(size: int) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def save_png(image: Image.Image, name: str) -> Path:
    ASSETS.mkdir(parents=True, exist_ok=True)
    path = ASSETS / name
    image.save(path, "PNG", optimize=True)
    return path


def make_assets() -> dict[str, Path]:
    ASSETS.mkdir(parents=True, exist_ok=True)

    portrait = Image.new("RGB", (640, 896), "#c7d4df")
    d = ImageDraw.Draw(portrait)
    d.rectangle([0, 0, 640, 896], fill="#bccbd8")
    d.rectangle([120, 330, 520, 820], fill="#763126")
    d.ellipse([210, 105, 430, 325], fill="#edc7a5", outline="#38241d", width=4)
    d.rectangle([258, 322, 382, 820], fill="#1f2f43")
    d.line([120, 400, 35, 645], fill="#1f2f43", width=34)
    d.line([520, 400, 610, 630], fill="#1f2f43", width=34)
    d.line([276, 820, 210, 892], fill="#1f2f43", width=38)
    d.line([364, 820, 430, 892], fill="#1f2f43", width=38)
    d.ellipse([255, 185, 285, 215], fill="#101820")
    d.ellipse([355, 185, 385, 215], fill="#101820")
    d.arc([270, 215, 370, 290], 15, 165, fill="#7f1d1d", width=5)
    d.text((28, 28), "BASE PERSON", fill="#102033", font=font(32))

    face = Image.new("RGB", (640, 640), "#e8ded2")
    d = ImageDraw.Draw(face)
    d.rectangle([0, 0, 640, 640], fill="#eee1d5")
    d.ellipse([175, 70, 465, 440], fill="#d9a77f", outline="#2f1f1a", width=5)
    d.polygon([(180, 150), (320, 40), (460, 150), (450, 95), (320, 15), (190, 95)], fill="#3a2118")
    d.ellipse([245, 220, 285, 260], fill="#111827")
    d.ellipse([355, 220, 395, 260], fill="#111827")
    d.arc([250, 285, 390, 385], 20, 160, fill="#9d174d", width=7)
    d.text((34, 520), "SOURCE FACE", fill="#322018", font=font(34))

    ref1 = Image.new("RGB", (768, 512), "#16202c")
    d = ImageDraw.Draw(ref1)
    d.rectangle([0, 310, 768, 512], fill="#2c1d13")
    for x in range(0, 768, 84):
      d.rectangle([x, 120, x + 42, 512], fill="#394b5d")
      d.rectangle([x + 8, 145, x + 34, 168], fill="#ffd166")
    d.ellipse([520, 54, 610, 144], fill="#fdf6b2")
    d.text((26, 32), "CITY LIGHT REF", fill="#f8fafc", font=font(30))

    ref2 = Image.new("RGB", (640, 896), "#ecfdf5")
    d = ImageDraw.Draw(ref2)
    d.rectangle([0, 0, 640, 896], fill="#ecfdf5")
    d.rectangle([160, 280, 480, 810], fill="#16a34a")
    d.ellipse([230, 90, 410, 285], fill="#f3c7a6")
    d.text((34, 36), "CLOTHES REF", fill="#064e3b", font=font(32))

    sketch = Image.new("RGB", (768, 768), "#ffffff")
    d = ImageDraw.Draw(sketch)
    ink = "#111827"
    d.line([145, 610, 250, 435, 330, 610], fill=ink, width=18)
    d.ellipse([210, 220, 330, 340], outline=ink, width=18)
    d.line([270, 340, 270, 500], fill=ink, width=18)
    d.line([270, 390, 120, 395], fill=ink, width=15)
    d.line([270, 390, 470, 300], fill=ink, width=15)
    d.line([104, 200, 104, 615], fill=ink, width=16)
    for xy in ([78, 172, 104, 198], [116, 150, 146, 180], [150, 188, 180, 218]):
        d.ellipse(xy, fill=ink)

    mask = Image.new("RGB", (640, 896), "#000000")
    d = ImageDraw.Draw(mask)
    d.ellipse([185, 235, 455, 545], fill="#ffffff")

    wide = Image.new("RGB", (1024, 576), "#b8c5d1")
    d = ImageDraw.Draw(wide)
    d.rectangle([0, 300, 1024, 576], fill="#44503f")
    d.ellipse([660, 80, 805, 225], fill="#ffe7a0")
    d.rectangle([90, 210, 340, 530], fill="#7f1d1d")
    d.text((40, 40), "WIDE SOURCE", fill="#0f172a", font=font(38))

    return {
        "portrait": save_png(portrait, "base-person.png"),
        "face": save_png(face, "source-face.png"),
        "ref1": save_png(ref1, "city-ref.png"),
        "ref2": save_png(ref2, "clothes-ref.png"),
        "sketch": save_png(sketch, "sketch-stick-mage.png"),
        "mask": save_png(mask, "mask-body.png"),
        "wide": save_png(wide, "wide-source.png"),
    }


@dataclass
class Case:
    name: str
    body: dict[str, Any]


def build_cases(assets: dict[str, Path], pass_no: int) -> list[Case]:
    seed = 830000 + pass_no * 100
    base = {
        "provider": "comfyui",
        "negativePrompt": "",
        "steps": 4,
        "cfg": 1,
        "guidance": 3.5,
        "modelProfile": "local_flux_klein",
    }
    sketch_prompt = (
        "Transform this sketch into a hyper-realistic cinematic scene. Interpret the lines as real-world objects "
        "with high-quality textures, cinematic lighting, natural shadows, depth, realistic materials and clean composition. "
        "Preserve the exact composition, silhouettes, poses, proportions and spatial relationships from the sketch. "
        f"Scene description: pass {pass_no}, a young wizard training with a staff in a forest clearing."
    )
    return [
        Case("text_to_image", base | {
            "mode": "text_to_image",
            "prompt": f"Pass {pass_no}: cinematic realistic red teapot on a wooden table, warm window light, crisp details",
            "seed": seed + 1,
            "width": 768,
            "height": 512,
            "strength": 0.75,
        }),
        Case("image_to_image", base | {
            "mode": "image_to_image",
            "prompt": f"Pass {pass_no}: convert the source into a premium cyberpunk portrait, preserve pose and composition",
            "seed": seed + 2,
            "width": 640,
            "height": 896,
            "strength": 0.75,
            "inputImage1": data_url(assets["portrait"]),
        }),
        Case("edit_4_images", base | {
            "mode": "edit",
            "prompt": (
                f"Pass {pass_no}: Image 1 is the primary source. Preserve subject identity, pose and layout. "
                "Use Image 2 for night city lighting, Image 3 for green clothing color, Image 4 for wide cinematic mood."
            ),
            "seed": seed + 3,
            "width": 640,
            "height": 896,
            "strength": 0.75,
            "inputImage1": data_url(assets["portrait"]),
            "inputImages": [
                {"index": 1, "role": "base", "image": data_url(assets["portrait"])},
                {"index": 2, "role": "background", "image": data_url(assets["ref1"])},
                {"index": 3, "role": "clothing", "image": data_url(assets["ref2"])},
                {"index": 4, "role": "style", "image": data_url(assets["wide"])},
            ],
        }),
        Case("faceswap", base | {
            "mode": "faceswap",
            "prompt": (
                f"Pass {pass_no}: Replace the head in image 1 with the head from image 2, adapting facial features "
                "to match the artistic style, focus, and environmental lighting of image 1."
            ),
            "seed": seed + 4,
            "width": 640,
            "height": 896,
            "strength": 0.75,
            "inputImage1": data_url(assets["portrait"]),
            "inputImage2": data_url(assets["face"]),
            "loras": [],
        }),
        Case("paint_sketch", base | {
            "mode": "paint",
            "prompt": sketch_prompt,
            "seed": seed + 5,
            "width": 768,
            "height": 768,
            "strength": 0.75,
            "canvas": data_url(assets["sketch"]),
        }),
        Case("paint_mask", base | {
            "mode": "inpaint",
            "prompt": (
                f"Pass {pass_no}: Edit only the masked area. Replace it with a luminous blue crystal jacket, "
                "seamlessly blended with the surrounding person and lighting."
            ),
            "seed": seed + 6,
            "width": 640,
            "height": 896,
            "strength": 0.75,
            "inputImage1": data_url(assets["portrait"]),
            "maskImage": data_url(assets["mask"]),
        }),
        Case("paint_outpaint", base | {
            "mode": "outpaint",
            "prompt": (
                f"Pass {pass_no}: Extend the composition with a logical continuation of the scene, matching perspective, "
                "lighting, color palette and texture."
            ),
            "seed": seed + 7,
            "width": 1024,
            "height": 768,
            "strength": 0.75,
            "inputImage1": data_url(assets["wide"]),
            "outpaint": {"left": 160, "right": 160, "top": 96, "bottom": 96},
        }),
    ]


def wait_job(session: requests.Session, base_url: str, job_id: str, timeout_s: int) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    last: dict[str, Any] = {}
    while time.time() < deadline:
        response = session.get(f"{base_url}/api/jobs/{job_id}", timeout=30)
        response.raise_for_status()
        last = response.json()
        if last.get("status") in {"completed", "failed", "cancelled"}:
            return last
        time.sleep(5)
    raise TimeoutError(f"Job {job_id} timed out; last={last}")


def image_probe(url: str) -> dict[str, Any]:
    path = url.split("?", 1)[0]
    if path.startswith("/api/media/"):
        path = path.replace("/api/media/", "/media/", 1)
    if path.startswith("/"):
        path = str(ROOT / "backend" / path.lstrip("/").replace("/", "\\"))
    file_path = Path(path)
    if not file_path.exists():
        return {"exists": False, "path": str(file_path)}
    with Image.open(file_path) as image:
        stat = image.convert("RGB").resize((1, 1)).getpixel((0, 0))
        return {
            "exists": True,
            "path": str(file_path),
            "width": image.width,
            "height": image.height,
            "avg_rgb_sample": stat,
            "bytes": file_path.stat().st_size,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--passes", type=int, default=1)
    parser.add_argument("--base-url", default="https://izo.alikinas.ru")
    parser.add_argument("--session-file", default=str(LOGS / "codex-night-session.json"))
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    session_info = json.loads(Path(args.session_file).read_text(encoding="utf-8"))
    session = requests.Session()
    session.headers.update({"Cookie": session_info["cookies"], "User-Agent": "Codex acceptance test"})

    assets = make_assets()
    report: dict[str, Any] = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "base_url": args.base_url,
        "passes": args.passes,
        "assets": {k: str(v) for k, v in assets.items()},
        "results": [],
    }
    out_path = LOGS / f"acceptance-generation-{time.strftime('%Y%m%d-%H%M%S')}.json"

    for pass_no in range(1, args.passes + 1):
        for case in build_cases(assets, pass_no):
            started = time.time()
            entry: dict[str, Any] = {"pass": pass_no, "case": case.name, "mode": case.body["mode"], "seed": case.body["seed"]}
            print(f"[pass {pass_no}/{args.passes}] {case.name}: submit")
            try:
                response = session.post(f"{args.base_url}/api/generate", json=case.body, timeout=60)
                entry["submit_status"] = response.status_code
                if not response.ok:
                    entry["error"] = response.text[:1000]
                    raise RuntimeError(f"submit failed {response.status_code}: {response.text[:240]}")
                created = response.json()
                entry["job_id"] = created["id"]
                entry["tokenCost"] = created.get("tokenCost")
                entry["dailyTokensRemaining"] = created.get("dailyTokensRemaining")
                job = wait_job(session, args.base_url, created["id"], args.timeout)
                entry["job"] = {k: job.get(k) for k in ("id", "status", "progress", "message", "resultUrl", "resultImageId", "error")}
                if job.get("status") != "completed" or not job.get("resultUrl"):
                    raise RuntimeError(f"job failed: {entry['job']}")
                entry["image"] = image_probe(job["resultUrl"])
                entry["duration_s"] = round(time.time() - started, 1)
                print(f"[pass {pass_no}/{args.passes}] {case.name}: ok {entry['duration_s']}s {job.get('resultUrl')}")
            except Exception as exc:
                entry["failed"] = True
                entry["exception"] = str(exc)
                print(f"[pass {pass_no}/{args.passes}] {case.name}: FAILED {exc}")
                report["results"].append(entry)
                out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                raise
            report["results"].append(entry)
            out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    report["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report={out_path}")


if __name__ == "__main__":
    main()
