#!/usr/bin/env python3
"""
Recolour still pet images (green background stays), e.g. base pictures for Veo.

  python recolor_images.py base.png --to ginger black --pick-eyes
  python recolor_images.py base.png --to ginger black --eyes 'x1,y1,x2,y2,...;x1,y1,...'
  python recolor_images.py base.png --to ginger --chroma-max 0.24

Output: <name>_<colour>.png next to the source (or in --out-dir).
Uses the same Recolor as pet_pipeline.py, so stills and videos get the same tones.
"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pet_pipeline import Recolor, chroma_alpha, clean_alpha, pick_polygons, refine_matte  # noqa: E402


def recolor_image(bgr, palette, chroma_max, hue_tol, key="green", eyes=None):
    alpha = clean_alpha(chroma_alpha(bgr, key))
    bg = np.median(bgr[alpha < 0.02].astype(np.float32), axis=0)
    fg, alpha = refine_matte(bgr, alpha)
    bgra = np.dstack([fg, (alpha * 255).astype(np.uint8)])
    out = Recolor(palette, chroma_max, hue_tol)(bgra, eyes)[..., :3].astype(np.float32)
    a = alpha[..., None]
    return np.clip(out * a + bg * (1 - a), 0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+")
    ap.add_argument("--to", nargs="+", required=True, help="ginger black gray white brown or '#hex@0,...'")
    ap.add_argument("--out-dir")
    ap.add_argument("--chroma-max", type=float, default=0.4)
    ap.add_argument("--hue-tol", type=float, default=45.0)
    ap.add_argument("--key", choices=["green", "blue"], default="green")
    ap.add_argument("--eyes", help="eye outlines in pixels 'x1,y1,x2,y2,...;...' (or boxes 'x,y,w,h')")
    ap.add_argument("--pick-eyes", action="store_true", help="click eye outlines with the mouse")
    args = ap.parse_args()
    for p in map(Path, args.images):
        bgr = cv2.imread(str(p))
        if bgr is None:
            sys.exit(f"cannot read {p}")
        H, W = bgr.shape[:2]
        eyes = None
        if args.eyes:
            eyes = [[float(v) for v in e.split(",")] for e in args.eyes.split(";") if e.strip()]
        elif args.pick_eyes:
            eyes = pick_polygons(bgr, f"{p.name}: click around EACH EYE, Enter after each eye, Esc to finish")
            eyes = [[float(v) for pt in pl for v in pt] for pl in eyes]
            print("eyes:", ";".join(",".join(str(int(v)) for v in e) for e in eyes))
        if eyes:
            eyes = [[v / (W if i % 2 == 0 else H) for i, v in enumerate(e)] if len(e) >= 6
                    else [e[0] / W, e[1] / H, e[2] / W, e[3] / H] for e in eyes]
        for col in args.to:
            name = col if not col.startswith("#") else "custom"
            dst = Path(args.out_dir or p.parent) / f"{p.stem}_{name}.png"
            dst.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(dst), recolor_image(bgr, col, args.chroma_max, args.hue_tol, args.key, eyes))
            print("->", dst)


if __name__ == "__main__":
    main()
