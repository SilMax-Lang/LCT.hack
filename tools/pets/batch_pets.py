#!/usr/bin/env python3
"""
Process the whole pets source folder in one go.

Folder layout:  <root>/<пет>/<расцветка>/<возраст>/видео/<state>.mp4
If a colour has no videos, it is made by recolouring the source colour
(default: серый) of the same pet and age, so Veo is needed for 9 variants, not 27.

Usage:
  python batch_pets.py --root <папка с исходниками петов> --out assets/pets --quality both
  python batch_pets.py ... --only cat          # one pet
  python batch_pets.py ... --dry-run           # print commands only

Head box and eye outlines are taken, in this order, from
  <пет>/<source colour>/<возраст>/картинки/head_px.txt and eyes_px.txt
  (video pixels of the 1920x1080 source clips, crop-independent),
  then from head_px / eyes_px in an earlier pet.json of this pet or of the source colour.
If there is nothing, the first run opens windows to pick them (saved to pet.json as pixels).
The eye outlines are only a search zone: the eyes are found on every frame by colour.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

PETS = {"кот": "cat", "енот": "raccoon", "пес": "dog"}
COLOURS = {"рыжий": "ginger", "серый": "gray", "чёрный": "black"}
AGES = {"маленький": "small", "средний": "medium", "большой": "large"}
QUALITY = {
    "normal": ["--size", "512", "--fps", "12", "--quality", "85"],
    "ultra": ["--size", "1024", "--fps", "24", "--quality", "90"],
}
HERE = Path(__file__).resolve().parent


def find_dir(parent, name):
    """Match folder names regardless of macOS Unicode normalisation (й, ё)."""
    import unicodedata
    want = unicodedata.normalize("NFC", name)
    for d in parent.iterdir() if parent.exists() else []:
        if d.is_dir() and unicodedata.normalize("NFC", d.name) == want:
            return d
    return parent / name


def videos(folder):
    v = find_dir(folder, "видео")
    return sorted(p for p in v.glob("*.mp4")) if v.exists() else []


def run(cmd, dry):
    print("  $", " ".join(f'"{c}"' if " " in c else c for c in cmd))
    if not dry:
        subprocess.run(cmd, check=True)


def _manifest(out, tier, pet_id):
    p = Path(out) / tier / pet_id / "pet.json"
    return json.loads(p.read_text()) if p.exists() else {}


def head_of(out, tier, pet_id):
    h = _manifest(out, tier, pet_id).get("head_px")
    return ",".join(str(v) for v in h) if h else None


def eyes_of(out, tier, pet_id):
    e = _manifest(out, tier, pet_id).get("eyes_px")
    return ";".join(",".join(str(v) for v in poly) for poly in e) if e else None


def px_file(folder, name):
    p = find_dir(folder, "картинки") / name
    return p.read_text().strip() if p.exists() else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", default="assets/pets")
    ap.add_argument("--quality", choices=["normal", "ultra", "both"], default="normal")
    ap.add_argument("--source", default="серый", help="colour that has Veo videos")
    ap.add_argument("--only", help="cat / raccoon / dog")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--qa", action="store_true", help="qa_<state>.txt/.jpg for recoloured pets")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).expanduser()
    tiers = ["normal", "ultra"] if args.quality == "both" else [args.quality]
    py = sys.executable
    script = str(HERE / "pet_pipeline.py")
    done, skipped = [], []

    for pet_ru, pet_en in PETS.items():
        if args.only and args.only != pet_en:
            continue
        for age_ru, age_en in AGES.items():
            src_dir = find_dir(find_dir(find_dir(root, pet_ru), args.source), age_ru)
            src_videos = videos(src_dir)
            src_id = f"{pet_en}_{COLOURS[args.source]}_{age_en}"
            order = [args.source] + [c for c in COLOURS if c != args.source]  # source first: its head box is reused
            for col_ru in order:
                col_en = COLOURS[col_ru]
                pet_id = f"{pet_en}_{col_en}_{age_en}"
                own = videos(find_dir(find_dir(find_dir(root, pet_ru), col_ru), age_ru))
                clips = own or src_videos
                if not clips:
                    skipped.append(f"{pet_ru}/{col_ru}/{age_ru}")
                    continue
                recolor = [] if own else ["--recolor", col_en]
                print(f"\n== {pet_ru}/{col_ru}/{age_ru} -> {pet_id}"
                      + ("" if own else f" (перекраска из {args.source})"))
                for tier in tiers:
                    head = (px_file(src_dir, "head_px.txt") or head_of(args.out, "normal", pet_id)
                            or head_of(args.out, "normal", src_id))
                    cmd = [py, script, "--pet", pet_id, "--out", str(Path(args.out) / tier)] + QUALITY[tier]
                    cmd += recolor
                    cmd += ["--head-px", head] if head else ["--pick-head"]
                    eyes = (px_file(src_dir, "eyes_px.txt") or eyes_of(args.out, "normal", pet_id)
                            or eyes_of(args.out, "normal", src_id))
                    cmd += ["--eyes-px", eyes] if eyes else ["--pick-eyes"]
                    if args.qa and recolor:
                        cmd.append("--qa")
                    if recolor:
                        # eye masks from SAM 2.1: cached in видео/eyes/ (made where torch + sam2 are
                        # installed); without cache and without torch the colour eye finder is used
                        cmd.append("--sam")
                    if args.preview:
                        cmd.append("--preview")
                    cmd += [f"{p.stem}={p}" for p in clips]
                    run(cmd, args.dry_run)
                done.append(pet_id)

    print(f"\nготово: {len(done)}")
    if skipped:
        print("нет видео:", ", ".join(skipped))


if __name__ == "__main__":
    main()
