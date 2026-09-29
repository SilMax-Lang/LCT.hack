#!/usr/bin/env python3
"""
Veo -> Flutter pipeline for one pet.

Takes all clips of ONE pet (one colour), every clip generated on a green
backdrop with the same start/end frame, and produces:

  <out>/<pet>/<state>.webp        animated WebP with alpha, loops
  <out>/<pet>/<state>_poster.png  first frame (placeholder while loading)
  <out>/<pet>/pet.json            fps, frame counts, cut points, head track per frame
  <out>/<pet>/preview_<state>.mp4 (with --preview) tracking check on a checkerboard
  <out>/<pet>/qa_<state>.txt/.jpg (with --qa and --recolor) leftover spots per frame

All clips of a pet share one crop, so switching states in the app has no jump.
The head track is a similarity transform per frame (a, b, tx, ty) in
normalised coordinates, mapping frame-0 positions to frame-i positions:
    x' = a*x - b*y + tx
    y' = b*x + a*y + ty
An accessory placed on frame 0 follows the head via this transform.

Head and eyes are best given in VIDEO PIXELS (--head-px, --eyes-px: 1920x1080 frame of
an unscaled clip, e.g. idle). They do not depend on the crop, which changes whenever a
clip is added. --head / --eyes (fractions of the output frame) still work but break when
the crop changes.

Recolor with --sam (recommended): eye masks from SAM 2.1 video segmentation (Meta, Apache 2.0;
pip install torch sam2, weights sam2.1_t.pt next to this script, e.g. from
github.com/ultralytics/assets/releases/download/v8.3.0/sam2.1_t.pt). The masks are cached in
<video folder>/eyes/<clip>_<size>_<fps>_<crop>.npz; with a cache torch is not needed. Inside the
mask the eye keeps all its colours. Without masks the colour eye finder below is used.

Recolor without SAM: the eye outline is only a search zone. On every frame the eyes are
found again by colour: pupil (very dark blob inside a ring of iris colour), iris
(colourful), eye white (bright, neutral) next to them. Iris, pupil and highlights keep
their colours, the eye white becomes neutral grey, everything else in the zone (eyelids,
fur, a closed or squinting eye) gets the fur palette.

Usage:
  python pet_pipeline.py --pet cat_ginger_medium --out assets/pets \\
      idle=idle.mp4 happy=happy@0.75.mp4 \\
      --head-px 653.7,1.6,649.6,558.3 --eyes-px "$(cat eyes_px_medium.txt)" \\
      --recolor ginger --preview --qa

Requires: pip install opencv-python pillow numpy   (rembg only for --matte rembg)
"""
import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


# ---------------------------------------------------------------- matting

def chroma_alpha(bgr, key="green", lo=0.18, hi=0.45):
    """Soft alpha from a green/blue screen. Brightness-normalised so that
    shadows on the backdrop are keyed out too."""
    f = bgr.astype(np.float32) / 255.0
    b, g, r = f[..., 0], f[..., 1], f[..., 2]
    if key == "green":
        k, o = g, np.maximum(r, b)
    else:
        k, o = b, np.maximum(r, g)
    spill = (k - o) / np.maximum(k, 0.15)
    alpha = 1.0 - np.clip((spill - lo) / (hi - lo), 0.0, 1.0)
    return alpha


class RembgMatte:
    def __init__(self):
        try:
            from rembg import new_session, remove
        except ImportError:
            sys.exit("--matte rembg needs: pip install rembg onnxruntime")
        self._remove = remove
        self._session = new_session("birefnet-general")

    def __call__(self, bgr):
        pil = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        mask = self._remove(pil, session=self._session, only_mask=True)
        return np.asarray(mask, dtype=np.float32) / 255.0


def make_plate(path, n=40):
    c=cv2.VideoCapture(path); N=int(c.get(7)); F=[]
    for i in np.linspace(0,N-1,n).astype(int):
        c.set(1,int(i)); ok,f=c.read()
        if ok: F.append(cv2.resize(f,(640,360),interpolation=cv2.INTER_AREA))
    FH,FW=int(c.get(4)),int(c.get(3))
    F=np.stack(F).astype(np.float32)
    b,g,r=F[...,0],F[...,1],F[...,2]
    spill=(g-np.maximum(r,b))/np.maximum(g,38)
    bg=spill>0.14
    # erode per frame so fur edges are not sampled
    bg=np.stack([cv2.erode(m.astype(np.uint8),np.ones((3,3),np.uint8))>0 for m in bg])
    cnt=bg.sum(0)
    acc=(F*bg[...,None]).sum(0)/np.maximum(cnt,1)[...,None]
    hole=(cnt<2).astype(np.uint8)
    # fill never-seen background (behind the body) smoothly from around
    small=cv2.resize(acc,(320,180),interpolation=cv2.INTER_AREA).astype(np.uint8)
    hs=cv2.resize(hole,(320,180),interpolation=cv2.INTER_NEAREST)
    hs=cv2.dilate(hs,np.ones((3,3),np.uint8))
    fill=cv2.inpaint(small,hs,15,cv2.INPAINT_TELEA)
    fill=cv2.resize(fill,(F.shape[2],F.shape[1]),interpolation=cv2.INTER_CUBIC).astype(np.float32)
    plate=np.where(hole[...,None]>0,fill,acc)
    plate=cv2.GaussianBlur(plate,(0,0),1)
    return cv2.resize(plate,(FW,FH),interpolation=cv2.INTER_CUBIC)
def diff_alpha(bgr, plate, t0=6., t1=30.):
    lab=cv2.cvtColor(bgr,cv2.COLOR_BGR2LAB).astype(np.float32)
    lp=cv2.cvtColor(np.clip(plate,0,255).astype(np.uint8),cv2.COLOR_BGR2LAB).astype(np.float32)
    d=lab-lp; d[...,0]*=0.2   # brightness counts less (soft shading on the backdrop)
    d=np.sqrt((d**2).sum(-1))
    return np.clip((d-t0)/(t1-t0),0,1)


# fur tint in Lab: L gain, a, b (OpenCV Lab: a,b offset 128)
TINTS = {
    "ginger": dict(gain=1.0, lift=0, a=24, b=46),
    "black":  dict(gain=0.58, lift=6, a=2, b=4),     # тёплый графит, не уголь
}
def ramp(x, x0, x1):
    return np.clip((x - x0) / (x1 - x0), 0, 1)

class RecolorLab:
    """Recolor the mid-tone fur only. Eyes (iris blobs + pupil + glint), mouth, very dark
    parts (nose, mask lines, pupils) and white markings keep their colours."""
    def __init__(self, name):
        self.t = TINTS[name]
        self.last = None
    def eye_mask(self, bgr, alpha):
        H, W = alpha.shape
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
        C = hsv[..., 1] * hsv[..., 2] / 65025.0; h = hsv[..., 0] * 2
        solid = alpha > 200
        ys = np.nonzero(solid.any(1))[0]
        top = ys.min() if len(ys) else 0; bot = ys.max() if len(ys) else H
        head = np.zeros_like(solid); head[top:top + int(0.55 * (bot - top))] = True
        iris = (C > 0.17) & (h > 5) & (h < 55) & solid & head
        iris = cv2.morphologyEx(iris.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        n, lab, st, _ = cv2.connectedComponentsWithStats(iris, 8)
        keep = np.zeros((H, W), np.uint8)
        s = W / 512
        for j in sorted(range(1, n), key=lambda j: -st[j, 4])[:2]:
            if st[j, 4] < 25 * s * s:
                continue
            hull = cv2.convexHull(cv2.findNonZero((lab == j).astype(np.uint8)))
            cv2.fillPoly(keep, [hull], 1)
        keep = cv2.dilate(keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(5 * s) | 1,) * 2))
        mouth = (C > 0.15) & ((h > 330) | (h < 5)) & solid & head
        keep |= mouth.astype(np.uint8)
        return keep
    def __call__(self, bgra):
        bgr, alpha = bgra[..., :3], bgra[..., 3]
        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB).astype(np.float32)
        L = lab[..., 0]
        w = ramp(L, 35, 85) * (1 - 0.9 * ramp(L, 180, 225))
        keep = self.eye_mask(bgr, alpha)
        kf = cv2.GaussianBlur(keep.astype(np.float32), (0, 0), 1.0)
        w = w * (1 - kf)
        t = self.t
        # chroma fades towards the light end so fur tips stay soft
        cfade = 1 - 0.5 * ramp(L, 150, 230)
        out = lab.copy()
        out[..., 0] = np.clip(L * t["gain"] + t["lift"], 0, 255)
        out[..., 1] = 128 + t["a"] * cfade
        out[..., 2] = 128 + t["b"] * cfade
        res = out * w[..., None] + lab * (1 - w[..., None])
        # dark parts that are not kept (mask, nose) get a light touch of the tint
        dk = (1 - ramp(L, 35, 85)) * (1 - kf) * 0.15
        res[..., 1] += (128 + t["a"] - res[..., 1]) * dk
        res[..., 2] += (128 + t["b"] - res[..., 2]) * dk
        if t["gain"] < 1:  # black: darken the dark parts a little too
            res[..., 0] -= res[..., 0] * dk * 0.5
        o = bgra.copy()
        o[..., :3] = cv2.cvtColor(np.clip(res, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)
        self.last = keep
        return o


def fill_holes(alpha, depth=6):
    """Muted Gemini backdrops need a low key threshold; grey fur with a green reflection
    then turns see-through inside the pet. Everything deeper than `depth` px from the
    backdrop connected to the frame border becomes opaque (gaps between legs stay open)."""
    H, W = alpha.shape
    solid = cv2.morphologyEx((alpha >= 0.5).astype(np.uint8), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21)))
    tr = (1 - solid).astype(np.uint8)
    n, lab = cv2.connectedComponents(tr, connectivity=4)
    border = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    outside = np.isin(lab, border[border > 0])
    big = [j for j in range(1, n) if j not in border and (lab == j).sum() > 0.02 * H * W]
    outside |= np.isin(lab, big)  # large enclosed gaps (tail touching the body) stay open
    d = cv2.distanceTransform((~outside).astype(np.uint8), cv2.DIST_L2, 5)
    return np.maximum(alpha, np.clip((d - depth) / 4.0, 0, 1)).astype(np.float32)


NO_KEEP_WHITE = False


def clean_alpha(alpha):
    """Drop specks: keep connected blobs >= 2% of the largest one."""
    solid = (alpha > 0.5).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(solid, 8)
    if n <= 1:
        return alpha
    areas = stats[1:, cv2.CC_STAT_AREA]
    keep_ids = np.where(areas >= 0.02 * areas.max())[0] + 1
    keep = np.isin(labels, keep_ids).astype(np.uint8)
    keep = cv2.dilate(keep, np.ones((7, 7), np.uint8))  # keep soft fur edges
    return alpha * keep


def refine_matte(bgr, alpha, band=None, plate=None):
    """Fix the soft edge. A chroma key underestimates transparency where tinted fur
    (e.g. blue-grey) mixes with green: the mix looks teal, not green, so it stays
    opaque and shows as a grey rim. In a thin band along the outline every pixel is
    unmixed against the backdrop colour B and the nearest inner fur colour F:
        alpha = <P-B, F-B> / |F-B|^2,  fg = (P - (1-alpha) B) / alpha
    Returns (fg_bgr, alpha)."""
    H, W = alpha.shape
    k = band or max(5, int(round(0.007 * max(H, W))))
    img = bgr.astype(np.float32)
    bgm = alpha < 0.02
    trans = (alpha < 0.5).astype(np.uint8)
    if bgm.sum() < 100 or trans.all() or not trans.any():
        return bgr, alpha
    B = np.median(img[bgm], axis=0)
    if plate is not None:
        B = None
    dist_in = cv2.distanceTransform(1 - trans, cv2.DIST_L2, 5)  # distance from the transparent area
    inner = ((trans == 0) & (dist_in >= k)).astype(np.uint8)
    if inner.sum() < 100:
        return bgr, alpha
    _, labels = cv2.distanceTransformWithLabels(1 - inner, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.where(inner == 1)  # labels follow raster order of the inner pixels
    edge = (alpha > 0.01) & (dist_in < k)
    idx = labels[edge] - 1
    smooth = cv2.GaussianBlur(img, (0, 0), 2)
    F = smooth[ys[idx], xs[idx]]
    P = img[edge]
    if B is None:
        B = plate.astype(np.float32)[edge]
    d = F - B
    a = np.clip(((P - B) * d).sum(1) / np.maximum((d * d).sum(1), 1.0), 0, 1)
    # the projection mistakes fur that is simply darker than its neighbours (shadow under
    # the paws) for a mix with the backdrop; only a pixel that is greener than the fur can
    # be see-through, so alpha is also estimated from the green excess and the larger wins
    def excess(c):
        return c[..., 1] - np.maximum(c[..., 0], c[..., 2])
    eB, eF, eP = excess(B), excess(F), excess(P)
    a_green = 1 - np.clip((eP - eF) / np.maximum(eB - eF, 1.0), 0, 1)
    a = np.maximum(a, a_green)
    a[a < 0.04] = 0
    out_a = alpha.copy()
    out_a[edge] = a
    fg = img.copy()
    aa = a[:, None]
    un = (P - (1 - aa) * B) / np.maximum(aa, 1e-3)
    w = np.clip((aa - 0.15) / 0.35, 0, 1)  # low alpha: unmixing is noisy, lean on F
    fg[edge] = np.clip(un * w + F * (1 - w), 0, 255)
    return fg.astype(np.uint8), out_a


def despill(bgr, alpha, key="green"):
    """Remove backdrop colour from semi-transparent edge pixels only, so
    green or blue details inside the pet are not touched."""
    band = ((alpha > 0.0) & (alpha < 0.98)).astype(np.uint8)
    band = cv2.dilate(band, np.ones((5, 5), np.uint8)).astype(bool)
    out = bgr.copy()
    b, g, r = out[..., 0], out[..., 1], out[..., 2]
    if key == "green":
        # average limit: a blue-grey fur edge mixed with green turns teal (g ~ b > r),
        # max(r, b) would keep that teal rim
        lim = ((r.astype(np.uint16) + b) // 2).astype(np.uint8)
        g[band] = np.minimum(g[band], lim[band])
    else:
        lim = np.maximum(r, g)
        b[band] = np.minimum(b[band], lim[band])
    return out


# ---------------------------------------------------------------- recolor

# Gradient maps: fur luminance 0..1 -> colour (BGR hex given as RGB "#rrggbb").
PALETTES = {
    "ginger": ["#2a1206@0", "#7a3410@0.3", "#d0702a@0.62", "#f6b56a@0.85", "#fff1dc@1"],
    "black": ["#060607@0", "#17171b@0.35", "#34343b@0.7", "#8c8d96@1"],
    "gray": ["#1e1f24@0", "#4b4d57@0.35", "#8a8c98@0.7", "#e6e7ee@1"],
    "white": ["#6b6a70@0", "#b9b8c0@0.35", "#e6e5ea@0.7", "#ffffff@1"],
    "brown": ["#1a0e08@0", "#4a2a18@0.35", "#8a5a38@0.7", "#e8cfb4@1"],
}


def parse_palette(spec):
    stops = PALETTES.get(spec)
    if stops is None:
        stops = [s.strip() for s in spec.split(",")]
    pos, col = [], []
    for s in stops:
        c, p = s.split("@")
        c = c.lstrip("#")
        col.append([int(c[4:6], 16), int(c[2:4], 16), int(c[0:2], 16)])  # BGR
        pos.append(float(p))
    lut = np.zeros((256, 3), np.float32)
    xs = np.linspace(0, 1, 256)
    for ch in range(3):
        lut[:, ch] = np.interp(xs, pos, [c[ch] for c in col])
    return lut


def colour_maps(bgr):
    """lum 0..255, chroma C = S*V 0..1, hue 0..360"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    lum = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return lum, hsv[..., 1] * hsv[..., 2] / 65025.0, hsv[..., 0] * 2.0


def move_poly(e, M, W, H):
    """Eye outline (normalised x1,y1,...) moved with the head transform -> pixel polygon."""
    a, b, tx, ty = M if M is not None else (1.0, 0.0, 0.0, 0.0)
    pts = np.array(e, np.float64).reshape(-1, 2)
    px = a * pts[:, 0] - b * pts[:, 1] + tx
    py = b * pts[:, 0] + a * pts[:, 1] + ty
    return np.stack([px * W, py * H], 1)


class EyeFinder:
    """Finds the visible eye on every frame, inside a search zone around the eye outline
    of frame 0 moved with the head track. The outline is only a hint: Veo moves and
    redraws the eyes against the head, and the output crop changes when a clip is added.

    In the source (grey) pet the fur is slightly tinted (C = S*V about 0.1, hue about 230),
    the eye white and the pupil are neutral and the iris is strongly coloured (C > 0.2).
    Open eye:
      iris   = coloured, not pink blobs; cut to a circle fitted (RANSAC) around the pupil,
               so rim light on the lower lid and iris-tinted eyelid do not count
      eye    = GrabCut from the iris (sure eye: iris, pupil, bright eye white; sure not-eye:
               tinted fur, pink, far away), then rays past the cut through the eye white in
               shadow up to the lid line (only sideways and never below the iris), convex fill
      keep   = iris, dark pixels, glints (original colours); the rest of the eye = neutral grey
    Half-closed eye (little iris): iris-hue pixels next to the dark slit keep their colour,
    the thick dark slit becomes dark neutral grey.
    Closed eye (no iris): nothing is protected, the lids get the fur palette."""

    def __init__(self, eyes, fur_hue=None):
        self.eyes = eyes
        self.fur_hue = fur_hue
        self.prev = [None] * len(eyes)  # eye of the previous frame, widens the zone

    def _slit(self, lum, chroma_s, hue, z, ew):
        """Half-closed eye: iris-hue pixels (hue at least 12 degrees from the fur hue towards
        blue/green, C > 0.09) next to the dark slit, grown through the neutral slit (C < 0.08).
        Returns (eye, keep, seed) or None for a closed eye."""
        H, W = lum.shape
        fh = self.fur_hue or 230.0
        dh = (hue - fh + 180) % 360 - 180  # negative = towards green/cyan for blue-grey fur
        ell = lambda r: cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, int(round(r)) | 1),) * 2)
        irish = ((chroma_s > 0.09) & (dh < -12) & (dh > -60) & (lum > 15) & z).astype(np.uint8)
        # thin bluish fringes along a closed lid line are not an iris: 0.06 eye width opening
        irish = cv2.morphologyEx(irish, cv2.MORPH_OPEN, ell(0.06 * ew))
        darkn = cv2.dilate(((lum < 45) & z).astype(np.uint8), np.ones((5, 5), np.uint8))
        n, lab, st, _ = cv2.connectedComponentsWithStats(irish, 8)
        ok = [j for j in range(1, n) if st[j, 4] >= 0.004 * ew * ew and (darkn[lab == j] > 0).any()]
        seed = np.isin(lab, ok).astype(np.uint8)
        if seed.sum() < 0.006 * ew * ew:
            return None
        slit = (((chroma_s < 0.08) | (irish > 0)) & z).astype(np.uint8)
        lim = cv2.dilate(seed, ell(0.6 * ew))
        g = seed.copy()
        k3 = np.ones((3, 3), np.uint8)
        for _ in range(int(0.3 * ew)):
            nxt = cv2.dilate(g, k3) & slit & lim
            if (nxt == g).all():
                break
            g = nxt
        g = cv2.morphologyEx(g, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)) | seed
        # iris keeps its colour; dark slit and light eye white become neutral
        return g, seed, seed

    @staticmethod
    def _iris_disc(seed, lum, z, ew, rng=np.random.default_rng(0)):
        H, W = seed.shape
        dark = ((lum < 50) & z).astype(np.uint8)
        ell = lambda r: cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, int(round(r)) | 1),) * 2)
        pupil = cv2.morphologyEx(dark, cv2.MORPH_OPEN, ell(0.15 * ew))
        n, lab, st, _ = cv2.connectedComponentsWithStats(pupil, 8)
        best, bj = 0.0, -1
        for j in range(1, n):
            if st[j, 4] < 0.02 * ew * ew:
                continue
            comp = (lab == j).astype(np.uint8)
            ring = (cv2.dilate(comp, ell(0.1 * ew)) & (1 - dark)) > 0
            fr = float(seed[ring].mean()) if ring.any() else 0.0
            if fr > best:
                best, bj = fr, j
        if bj < 0 or best < 0.25:
            return None
        blob = (lab == bj).astype(np.uint8)
        blob = blob | (seed & cv2.dilate(blob, ell(0.45 * ew)))
        cs, _ = cv2.findContours(blob, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        pts = max(cs, key=len)[:, 0, :].astype(np.float64)
        if len(pts) < 12:
            return None
        best_in, best_c = -1, None
        for _ in range(200):
            p = pts[rng.choice(len(pts), 3, replace=False)]
            A = np.array([[2 * (p[1, 0] - p[0, 0]), 2 * (p[1, 1] - p[0, 1])],
                          [2 * (p[2, 0] - p[0, 0]), 2 * (p[2, 1] - p[0, 1])]])
            bb = np.array([p[1] @ p[1] - p[0] @ p[0], p[2] @ p[2] - p[0] @ p[0]])
            if abs(np.linalg.det(A)) < 1e-6:
                continue
            c = np.linalg.solve(A, bb)
            r = np.linalg.norm(p[0] - c)
            if not (0.2 * ew < r < 0.7 * ew):
                continue
            inl = np.abs(np.linalg.norm(pts - c, axis=1) - r) < 1.5
            if inl.sum() > best_in:
                best_in, best_c = inl.sum(), (c, r, inl)
        if best_c is None or best_in < 0.3 * len(pts):
            return None
        c, r, inl = best_c
        # refine on the inliers (algebraic fit)
        q = pts[inl]
        A = np.c_[2 * q, np.ones(len(q))]
        sol = np.linalg.lstsq(A, (q ** 2).sum(1), rcond=None)[0]
        c = sol[:2]
        r = math.sqrt(max(sol[2] + c @ c, 1.0))
        disc = np.zeros((H, W), np.uint8)
        cv2.circle(disc, (int(round(c[0])), int(round(c[1]))), int(round(r + 1.5 + 0.06 * ew)), 1, -1)
        return disc, (lab == bj).astype(np.uint8)

    @staticmethod
    def _extend(eye, seed, lum, stop, ew, zone, n_rays=96):
        H, W = eye.shape
        ell = lambda r: cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, int(round(r)) | 1),) * 2)
        bh = cv2.morphologyEx(lum, cv2.MORPH_BLACKHAT, ell(0.18 * ew))
        bar = (lum < 70) | (bh > 30)
        ys, xs = np.nonzero(seed)
        cx, cy = xs.mean(), ys.mean()
        near_iris = cv2.dilate(seed, np.ones((5, 5), np.uint8)) > 0
        step = 0.5
        rmax = 1.3 * ew
        rs = np.arange(0, rmax, step)
        R = np.zeros(n_rays)
        for k in range(n_rays):
            t = 2 * math.pi * k / n_rays
            px = np.clip(np.round(cx + rs * math.cos(t)).astype(int), 0, W - 1)
            py = np.clip(np.round(cy + rs * math.sin(t)).astype(int), 0, H - 1)
            inside = eye[py, px] > 0
            idx = np.nonzero(inside)[0]
            r_gc = rs[idx[-1]] if len(idx) else 0.0
            i = int(r_gc / step) + 1
            # jump the dark ring around the iris (only where the cut ends at the iris; at the
            # eye white the dark pixels are the lid line)
            j = i
            if len(idx) and near_iris[py[idx[-1]], px[idx[-1]]] and abs(math.cos(t)) > 0.7:
                while j < len(rs) and rs[j] - r_gc < 0.12 * ew and bar[py[j], px[j]]:
                    j += 1
            r_ext = r_gc
            found = False
            # eye white in shadow at the sides of the iris is darker than the lids above it
            lmin = 75 if abs(math.cos(t)) > 0.7 else 100
            while j < len(rs) and rs[j] - r_gc < 0.35 * ew:
                yy, xx = py[j], px[j]
                if bar[yy, xx]:
                    found = True
                    break
                if stop[yy, xx] or not zone[yy, xx] or lum[yy, xx] < lmin:
                    break
                r_ext = rs[j]
                j += 1
            R[k] = r_ext if found else r_gc
        # radial median over 5 rays: single rays through gaps in the lid line do not count
        Rm = np.array([np.median(np.take(R, range(k - 2, k + 3), mode="wrap")) for k in range(n_rays)])
        pts = np.array([[cx + Rm[k] * math.cos(2 * math.pi * k / n_rays), cy + Rm[k] * math.sin(2 * math.pi * k / n_rays)]
                        for k in range(n_rays)])
        poly = np.zeros_like(eye)
        cv2.fillPoly(poly, [pts.round().astype(np.int32)], 1)
        return eye | (poly & zone)

    def __call__(self, bgr, alpha, M):
        H, W = alpha.shape
        lum, chroma, hue = colour_maps(bgr)
        chroma_s = cv2.blur(chroma, (3, 3))
        keep = np.zeros((H, W), np.float32)     # iris, pupil, glints: original colours
        neutral = np.zeros((H, W), np.float32)  # eye white: neutral grey
        eyes_m = np.zeros((H, W), np.uint8)
        info = []
        solid = (alpha > 128).astype(np.uint8)
        pink = (np.abs((hue - 350 + 180) % 360 - 180) < 45) & (chroma > 0.08)  # nose, inner ear, mouth
        ell = lambda r: cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, int(round(r)) | 1),) * 2)
        k3 = np.ones((3, 3), np.uint8)
        for ei, e in enumerate(self.eyes):
            poly = move_poly(e, M, W, H)
            ew = max(8.0, float(np.ptp(poly[:, 0])))  # eye width in px
            zone = np.zeros((H, W), np.uint8)
            cv2.fillPoly(zone, [poly.round().astype(np.int32)], 1)
            zone = cv2.dilate(zone, ell(0.6 * ew))
            if self.prev[ei] is not None:
                zone |= cv2.dilate(self.prev[ei], ell(0.3 * ew))
            zone &= solid
            z = zone > 0
            iris = ((chroma > 0.2) & (lum > 20) & ~pink & z).astype(np.uint8)
            n, lab, st, _ = cv2.connectedComponentsWithStats(iris, 8)
            seed = np.zeros((H, W), np.uint8)
            for j in range(1, n):
                if st[j, 4] >= 0.006 * ew * ew:
                    seed |= (lab == j).astype(np.uint8)
            # the iris is a disc around the pupil: a circle fitted (RANSAC) to the outline of
            # pupil + iris cuts off iris-coloured rim light on the lower lid and fur tint that
            # touches the iris; the straight lid cut of a half-closed eye is ignored as outliers
            res = self._iris_disc(seed, lum, z, ew)
            rim = np.zeros((H, W), bool)
            if res is not None:
                disc, pupil = res
                rim = (seed > 0) & (disc == 0)  # iris colour outside the iris: lid rim light
                seed &= disc
                # iris-tinted eyelid over the top of the iris is cut from the iris by the dark
                # lid line: only iris pieces joined to the pupil (not across dark pixels) stay
                n, lab, st, _ = cv2.connectedComponentsWithStats(seed, 4)
                touch = np.unique(lab[(cv2.dilate(pupil, k3) > 0) & (seed > 0)])
                big = [j for j in range(1, n) if st[j, 4] >= 0.03 * ew * ew]
                seed = np.isin(lab, [t for t in touch if t > 0] + big).astype(np.uint8)
            if seed.sum() < 0.02 * ew * ew:
                # half-closed eye: the iris is in the shadow of the lid, less colourful, but its
                # hue stays bluer (or greener) than the fur; no such iris next to a dark slit =
                # closed eye, everything gets the palette
                inpoly = np.zeros((H, W), np.uint8)
                cv2.fillPoly(inpoly, [poly.round().astype(np.int32)], 1)
                inpoly = cv2.dilate(inpoly, ell(0.15 * ew)) & solid
                slit = self._slit(lum, chroma_s, hue, inpoly > 0, ew)
                if slit is None:
                    info.append(0.0)
                    self.prev[ei] = None
                    continue
                eye, sk, sseed = slit
                near = cv2.dilate(sseed, ell(0.35 * ew)) & inpoly
                # the dark slit (pupil and iris in the lid shadow) becomes dark neutral grey (the
                # original is blue-grey, the palette would turn it brown); only thick dark parts
                # count, thin dark fur strokes are left to the palette
                dk = ((lum < 60) & (chroma_s < 0.08) & (near > 0)).astype(np.uint8)
                thick = cv2.morphologyEx(dk, cv2.MORPH_OPEN, ell(0.08 * ew))
                n, lab, st, _ = cv2.connectedComponentsWithStats(dk, 8)
                ids = np.unique(lab[thick > 0])
                slit_dark = np.isin(lab, ids[ids > 0]).astype(np.uint8) & cv2.dilate(thick, ell(0.1 * ew))
                keep = np.maximum(keep, sk.astype(np.float32))
                light = (eye & (1 - sk) & ((lum > 150) & (chroma_s < 0.08)).astype(np.uint8))
                neutral = np.maximum(neutral, np.maximum(slit_dark, light).astype(np.float32))
                eyes_m |= eye | slit_dark
                self.prev[ei] = eye
                info.append(-round(float(eye.sum()) / (ew * ew), 3))
                continue
            # graph cut (GrabCut) in a window around the iris: sure eye = iris, the pupil
            # inside the iris ring and the bright eye white next to it; sure not-eye = tinted
            # fur (the eye white and the pupil are neutral), pink details and anything far
            # from the iris; the cut runs along the lid lines between them
            hull = np.zeros((H, W), np.uint8)
            cv2.fillPoly(hull, [cv2.convexHull(cv2.findNonZero(seed))], 1)
            near = cv2.dilate(hull, ell(0.7 * ew))
            x, y, w_, h_ = cv2.boundingRect(near)
            gc = np.full((H, W), cv2.GC_BGD, np.uint8)
            win = (slice(y, y + h_), slice(x, x + w_))
            gc[win] = cv2.GC_PR_BGD
            gc[(cv2.dilate(hull, ell(0.3 * ew)) > 0)] = cv2.GC_PR_FGD
            fur_tint = (chroma_s > 0.095) & (np.abs((hue - (self.fur_hue or 230) + 180) % 360 - 180) < 25) \
                & (lum > 45) & (lum < 215)
            gc[fur_tint & (seed == 0)] = cv2.GC_BGD
            gc[cv2.dilate(rim.astype(np.uint8), k3) > 0] = cv2.GC_BGD
            gc[pink | (alpha < 128) | (near == 0)] = cv2.GC_BGD
            whites = ((lum > 190) & (chroma_s < 0.05)).astype(np.uint8)
            whites = cv2.morphologyEx(whites, cv2.MORPH_OPEN, ell(0.1 * ew)) & cv2.dilate(hull, ell(0.25 * ew))
            gc[(seed > 0) | ((lum < 45) & (hull > 0)) | (whites > 0)] = cv2.GC_FGD
            bgm, fgm = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
            sub = gc[win].copy()
            try:
                cv2.grabCut(np.ascontiguousarray(bgr[win]), sub, None, bgm, fgm, 4, cv2.GC_INIT_WITH_MASK)
            except cv2.error:
                pass
            eye = np.zeros((H, W), np.uint8)
            eye[win] = ((sub == cv2.GC_FGD) | (sub == cv2.GC_PR_FGD)).astype(np.uint8)
            eye = cv2.morphologyEx(eye, cv2.MORPH_OPEN, ell(0.06 * ew))
            n, lab, st, _ = cv2.connectedComponentsWithStats(eye, 8)
            eye = np.isin(lab, [j for j in range(1, n) if (seed[lab == j] > 0).any()]).astype(np.uint8)
            gc_eye = eye.copy()
            # eye white in shadow (tinted like the cheek) is often left out by the cut. Rays
            # from the iris centre go on past the cut boundary (jumping the dark ring around
            # the iris) through light, not fur-tinted pixels until the lid line (dark, or
            # darker than around: black-hat); a ray that finds no lid line within 0.35 eye
            # width ran into the fur and stays at the cut boundary
            if eye.any():
                eye = self._extend(eye, seed, lum, fur_tint | pink, ew, zone)
                # the eye opening is convex: notches left in it are filled with anything that
                # is not tinted fur and not the dark lid line
                eye = cv2.morphologyEx(eye, cv2.MORPH_CLOSE, ell(0.15 * ew))
                cvx = np.zeros_like(eye)
                cv2.fillPoly(cvx, [cv2.convexHull(cv2.findNonZero(eye))], 1)
                ytop = int(np.nonzero(seed)[0].min())
                cvx[:ytop] = 0  # above the iris: eyelid, never filled
                eye |= cvx & (~fur_tint & ~pink & (lum >= 75)).astype(np.uint8) & zone
                # below the iris the lower lid follows: nothing is added there beyond the cut
                # (the jump over the dark ring would cross the lid line into the cheek)
                ybot = int(np.nonzero(seed)[0].max())
                eye[ybot + 1:] = gc_eye[ybot + 1:]
                # narrow tails (along the lower lid, into the cheek) are cut off
                eye = cv2.morphologyEx(eye, cv2.MORPH_OPEN, ell(0.2 * ew)) | seed
            cs, _ = cv2.findContours(eye, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            eye = np.zeros_like(eye)
            cv2.drawContours(eye, cs, -1, 1, -1)
            eye |= seed
            # the pupil may reach past the found eye (under the lid shadow): very dark pixels
            # joined to the eye stay dark neutral instead of dark brown
            dk = ((lum < 40) & z).astype(np.uint8)
            n, lab, st, _ = cv2.connectedComponentsWithStats(dk, 8)
            touch = np.unique(lab[(cv2.dilate(eye, k3) > 0) & (dk > 0)])
            dk = np.isin(lab, [t for t in touch if t > 0]).astype(np.uint8) & cv2.dilate(eye, ell(0.25 * ew))
            eye &= (~(rim | ((chroma_s > 0.15) & (seed == 0)))).astype(np.uint8)
            k = ((seed | (lum < 60) | ((lum > 200) & (chroma < 0.15))) & (eye > 0)).astype(np.float32)
            eye = eye | dk
            keep = np.maximum(keep, k)
            neutral = np.maximum(neutral, eye.astype(np.float32) * (1 - k))
            eyes_m |= eye
            self.prev[ei] = eye
            info.append(round(float(eye.sum()) / (ew * ew), 3))
        keep = cv2.GaussianBlur(keep, (3, 3), 0)
        neutral = cv2.GaussianBlur(neutral, (3, 3), 0) * (1 - keep)
        return keep, neutral, eyes_m, info


def sam_eye_masks(frames, eyes, track, weights, res=512, config="configs/sam2.1/sam2.1_hiera_t.yaml"):
    """Eye masks with SAM 2.1 video segmentation (pip install torch sam2; weights
    sam2.1_hiera_tiny, e.g. sam2.1_t.pt). Frame 0: a box around every eye outline (the pet
    starts in the base pose with open eyes); SAM carries each mask through the clip, so a
    squint narrows it and a closed eye empties it. Runs on a face crop scaled to `res`.
    Returns uint8 array (frames, eyes, S, S)."""
    import os
    import tempfile
    import torch
    from sam2.build_sam import build_sam2_video_predictor
    n, S = len(frames), frames[0].shape[0]
    pts = np.vstack([move_poly(e, track[i] if track else None, S, S) for i in range(n) for e in eyes])
    ew = float(np.ptp(move_poly(eyes[0], track[0] if track else None, S, S)[:, 0]))
    x0, y0 = np.floor(pts.min(0) - 0.8 * ew).astype(int)
    x1, y1 = np.ceil(pts.max(0) + 0.8 * ew).astype(int)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(S, x1), min(S, y1)
    sc = res / max(x1 - x0, y1 - y0)
    out = np.zeros((n, len(eyes), S, S), np.uint8)
    with tempfile.TemporaryDirectory() as jd:
        for i, f in enumerate(frames):
            c = over_gray(f, 128)[y0:y1, x0:x1]
            cv2.imwrite(os.path.join(jd, f"{i:05d}.jpg"), cv2.resize(c, None, fx=sc, fy=sc, interpolation=cv2.INTER_CUBIC),
                        [cv2.IMWRITE_JPEG_QUALITY, 95])
        pred = build_sam2_video_predictor(config, weights, device="cpu",
                                          hydra_overrides_extra=[f"++model.image_size={res}"])
        with torch.inference_mode():
            state = pred.init_state(video_path=jd)
            for k, e in enumerate(eyes):
                p = (move_poly(e, track[0] if track else None, S, S) - [x0, y0]) * sc
                box = np.array([p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max()], np.float32)
                pred.add_new_points_or_box(state, frame_idx=0, obj_id=k + 1, box=box)
            for fi, oids, logits in pred.propagate_in_video(state):
                for j, o in enumerate(oids):
                    m = (logits[j, 0] > 0).cpu().numpy().astype(np.uint8)
                    out[fi, o - 1, y0:y1, x0:x1] = cv2.resize(m, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)
    return out


def eye_keep_from_masks(masks, alpha, lum):
    """SAM eye masks of one frame -> soft keep map: holes filled, the dark pupil inside the
    convex hull of the mask added (SAM sometimes leaves it out at the edge), 1 px eroded so
    the lid line and fur at the edge get the palette, feathered edge."""
    S = alpha.shape[0]
    keep = np.zeros(alpha.shape, np.uint8)
    dark = (lum < 50).astype(np.uint8)
    for m in masks:
        cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cs = [c for c in cs if cv2.contourArea(c) > 4 * (S / 512) ** 2]
        if not cs:
            continue
        cv2.drawContours(keep, cs, -1, 1, -1)
        hull = np.zeros_like(keep)
        cv2.fillPoly(hull, [cv2.convexHull(np.vstack(cs))], 1)
        keep |= hull & dark
    k = max(1, int(round(S / 512)))
    keep = cv2.erode(keep, np.ones((2 * k + 1, 2 * k + 1), np.uint8)) & (alpha > 128).astype(np.uint8)
    return keep, cv2.GaussianBlur(keep.astype(np.float32), (2 * k + 1, 2 * k + 1), 0)


class Recolor:
    """Gradient-map the fur, keep coloured details (nose, inner ears, mouth), white
    highlights and the eyes found by EyeFinder.

    Fur is found by colourfulness C = S*V and hue: pixels close to the fur hue may
    be up to `chroma_max` colourful (tinted fur, e.g. blue-grey), other hues only
    up to 0.16 (pink ears and nose stay). Fur hue and luminance range are measured
    once on the first frame, so all frames and clips get the same tones."""

    def __init__(self, palette, chroma_max=0.4, hue_tol=45.0):
        self.lut = parse_palette(palette)
        self.chroma_max, self.hue_tol = chroma_max, hue_tol
        self.fur_hue = None  # degrees, None = neutral grey fur
        self.lo = self.hi = None
        self.finder = None
        self.last = None  # (keep, neutral, hulls, info) of the last frame, for QA

    def _weight(self, bgr, alpha):
        lum, c, h = colour_maps(bgr)
        v = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[..., 2].astype(np.float32) / 255.0
        if self.lo is None:  # first frame: measure fur hue
            body = (alpha > 128) & (c < 0.25)
            tinted = body & (c > 0.04)
            if tinted.sum() > 0.3 * max(body.sum(), 1):
                ang = np.deg2rad(h[tinted])
                self.fur_hue = float(np.rad2deg(np.arctan2(np.sin(ang).mean(), np.cos(ang).mean())) % 360)
        if self.fur_hue is None:
            near = np.zeros_like(h)
        else:
            d = np.abs((h - self.fur_hue + 180) % 360 - 180)
            near = 1 - np.clip((d - self.hue_tol) / 30.0, 0, 1)
        # other hues count as fur while they are only slightly coloured (c < 0.16): this
        # takes in the purple-grey rim around the pink inner ear and the nose
        cmax = 0.16 + (self.chroma_max - 0.16) * near
        w = 1 - np.clip((c - cmax) / 0.06, 0, 1)
        # green backdrop reflected in the fur (feet, belly): it is fur, never a detail
        dg = np.abs((h - 125 + 180) % 360 - 180)
        w = np.maximum(w, 1 - np.clip((dg - 45) / 15.0, 0, 1))
        white = np.clip((v - 0.82) / 0.08, 0, 1) * (c < 0.12) * (0.0 if NO_KEEP_WHITE else 1.0)
        return w * (1 - white)

    def __call__(self, bgra, eyes=None, M=None, eye_masks=None):
        bgr, alpha = bgra[..., :3], bgra[..., 3]
        w = self._weight(bgr, alpha)
        lum = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        if self.lo is None:  # fur luminance range, measured once on solid fur pixels
            m = (alpha > 230) & (w > 0.8)
            vals = lum[m] if m.sum() > 100 else lum[alpha > 128]
            self.lo, self.hi = np.percentile(vals, 1), np.percentile(vals, 99)
        # soft edge pixels are fur mixed with backdrop: recolour them fully, otherwise
        # the original fur colour stays as a thin rim around the pet
        a = alpha.astype(np.float32) / 255.0
        w = np.maximum(w, 1 - np.clip((a - 0.6) / 0.35, 0, 1))
        keep = neutral = None
        if eye_masks is not None:  # SAM: the found eye keeps all its colours
            hulls, keep = eye_keep_from_masks(eye_masks, alpha, lum)
            neutral = np.zeros_like(keep)
            self.last = (keep, neutral, hulls, [round(float(m.sum()) / max(1, alpha.shape[0]) ** 2 * 100, 3) for m in eye_masks])
        elif eyes:
            if self.finder is None:
                self.finder = EyeFinder(eyes, self.fur_hue)
            keep, neutral, hulls, info = self.finder(bgr, alpha, M)
            self.last = (keep, neutral, hulls, info)
        t = np.clip((lum - self.lo) / max(self.hi - self.lo, 1.0), 0, 1)
        mapped = self.lut[(t * 255).astype(np.uint8)]
        w = w[..., None]
        out = bgra.copy()
        src = bgr.astype(np.float32)
        res = mapped * w + src * (1 - w)
        if keep is not None:
            # eye: iris/pupil/glints original, eye white neutral grey, the rest as above; the
            # three weights add up to 1, so a soft mask edge never lets the original through
            tint = self.lut[-1] / max(float(self.lut[-1].mean()), 1.0)  # light end of the palette
            grey = lum[..., None] * (0.85 + 0.15 * tint)
            k = keep[..., None]
            n = np.minimum(neutral[..., None], 1 - k)
            res = src * k + grey * n + res * (1 - k - n)
        out[..., :3] = np.clip(res, 0, 255).astype(np.uint8)
        return out


def qa_spots(out_bgra, hulls, palette, size):
    """Leftovers of the original blue-grey fur (or neutral grey patches) on a recoloured
    frame, outside the eyes. Returns list of (x, y, area) in output pixels."""
    if palette in ("gray", "white"):
        return []
    bgr, a = out_bgra[..., :3], out_bgra[..., 3]
    lum, c, h = colour_maps(bgr)
    blue = (h > 170) & (h < 290) & (c > (0.05 if palette != "black" else 0.08))
    grey = np.zeros_like(blue)
    if palette not in ("black",):
        grey = (c < 0.05) & (lum > 60) & (lum < 200)
    bad = (blue | grey) & (a > 230)
    s = max(1, size // 512)
    bad = cv2.morphologyEx(bad.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2 * s + 1, 2 * s + 1), np.uint8))
    bad &= (cv2.dilate(hulls, np.ones((3 * s, 3 * s), np.uint8)) == 0).astype(np.uint8)
    n, lab, st, cen = cv2.connectedComponentsWithStats(bad, 8)
    return [(int(cen[j, 0]), int(cen[j, 1]), int(st[j, 4])) for j in range(1, n) if st[j, 4] >= 4 * s * s]


def pick_polygons(img, title):
    """Click points along the outline of each eye (eye white included, eyelid line
    excluded). Enter = finish this eye, Backspace = undo point, Esc = done."""
    polys, cur = [], []

    def redraw():
        v = img.copy()
        for pl in polys:
            cv2.polylines(v, [np.array(pl, np.int32)], True, (0, 255, 0), 2)
        if cur:
            cv2.polylines(v, [np.array(cur, np.int32)], False, (0, 0, 255), 2)
            for p in cur:
                cv2.circle(v, p, 3, (0, 0, 255), -1)
        cv2.imshow(title, v)

    def on_mouse(ev, x, y, flags, param):
        if ev == cv2.EVENT_LBUTTONDOWN:
            cur.append((x, y))
            redraw()

    cv2.namedWindow(title, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(title, on_mouse)
    redraw()
    while True:
        k = cv2.waitKey(20) & 0xFF
        if k in (13, 10):
            if len(cur) >= 3:
                polys.append(list(cur))
            cur.clear()
            redraw()
        elif k == 27:
            if len(cur) >= 3:
                polys.append(list(cur))
            break
        elif k in (8, 127) and cur:
            cur.pop()
            redraw()
    cv2.destroyAllWindows()
    return polys


# ---------------------------------------------------------------- video io

def iter_sampled(path, fps_out, max_seconds):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        sys.exit(f"cannot open {path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    limit = total if total > 0 else 10 ** 9
    if max_seconds:
        limit = min(limit, int(round(max_seconds * src_fps)))
    next_t, idx = 0.0, 0
    while idx < limit:
        ok, frame = cap.read()
        if not ok:
            break
        t = idx / src_fps
        if t + 1e-6 >= next_t:
            yield frame
            next_t += 1.0 / fps_out
        idx += 1
    cap.release()


# ---------------------------------------------------------------- crop

def square_box(x0, y0, x1, y1, pad, align="bottom"):
    """Square crop around the pet. align=bottom puts the feet on the same line
    (pad above the bottom edge) for every pet, so pets of different growth
    stages stand on one floor line in the app."""
    w, h = x1 - x0, y1 - y0
    side = max(w, h) * (1 + 2 * pad)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    top = (y1 + pad * max(w, h) - side) if align == "bottom" else (cy - side / 2)
    return (int(round(cx - side / 2)), int(round(top)), int(round(side)))


def crop_rgba(bgr, alpha, box, size, k=1.0):
    x, y, side = box
    H, W = alpha.shape
    rgba = np.dstack([bgr.astype(np.float32), alpha * 255.0])
    if k != 1.0:  # undo the pet scale of a *_jump clip (scale 1/k around bottom centre)
        M = np.float32([[1 / k, 0, W / 2 - W / (2 * k) - x], [0, 1 / k, H - H / k - y]])
        rgba[..., :3] *= rgba[..., 3:4] / 255.0
        canvas = cv2.warpAffine(rgba, M, (side, side), flags=cv2.INTER_CUBIC,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        canvas[..., 3] = np.clip(canvas[..., 3], 0, 255)
        ca = canvas[..., 3:4] / 255.0
        canvas[..., :3] = np.where(ca > 1e-4, canvas[..., :3] / np.maximum(ca, 1e-4), 0)
    else:
        canvas = np.zeros((side, side, 4), np.float32)
        sx0, sy0 = max(x, 0), max(y, 0)
        sx1, sy1 = min(x + side, W), min(y + side, H)
        canvas[sy0 - y:sy1 - y, sx0 - x:sx1 - x] = rgba[sy0:sy1, sx0:sx1]
    # premultiply -> resize -> unpremultiply, avoids dark halos
    a = canvas[..., 3:4] / 255.0
    canvas[..., :3] *= a
    small = cv2.resize(canvas, (size, size), interpolation=cv2.INTER_AREA)
    a2 = small[..., 3:4] / 255.0
    small[..., :3] = np.where(a2 > 1e-4, small[..., :3] / np.maximum(a2, 1e-4), 0)
    return np.clip(small, 0, 255).astype(np.uint8)  # BGRA


def over_gray(bgra, gray=128):
    a = bgra[..., 3:4].astype(np.float32) / 255.0
    return (bgra[..., :3] * a + gray * (1 - a)).astype(np.uint8)


def checker(size, cell=16):
    yy, xx = np.mgrid[0:size, 0:size]
    c = (((xx // cell) + (yy // cell)) % 2) * 40 + 180
    return np.dstack([c, c, c]).astype(np.uint8)


# ---------------------------------------------------------------- tracking

def params_from_M(M):
    a, b = M[0, 0], M[1, 0]
    return np.array([math.log(max(math.hypot(a, b), 1e-6)), math.atan2(b, a), M[0, 2], M[1, 2]])


def M_from_params(p):
    s, r = math.exp(p[0]), p[1]
    a, b = s * math.cos(r), s * math.sin(r)
    return np.array([[a, -b, p[2]], [b, a, p[3]]], np.float64)


def lk(prev, cur, pts):
    nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev, cur, pts, None, winSize=(21, 21), maxLevel=3,
                                          criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
    back, st2, _ = cv2.calcOpticalFlowPyrLK(cur, prev, nxt, None, winSize=(21, 21), maxLevel=3)
    fb = np.linalg.norm((back - pts).reshape(-1, 2), axis=1)
    good = (st.reshape(-1) == 1) & (st2.reshape(-1) == 1) & (fb < 1.0)
    return nxt, good


def detect(gray, roi_mask):
    pts = cv2.goodFeaturesToTrack(gray, maxCorners=300, qualityLevel=0.005, minDistance=3, mask=roi_mask)
    return pts if pts is not None else np.zeros((0, 1, 2), np.float32)


def track_head(grays, alphas, head_px):
    """Similarity transform frame0 -> frame i for the head region.
    Chain LK tracking, then close the loop (last -> first) and spread the
    drift linearly, then smooth circularly."""
    n = len(grays)
    x, y, w, h = head_px
    H, W = grays[0].shape

    def roi_mask(M):
        corners = np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], np.float64)
        pc = corners @ M[:, :2].T + M[:, 2]
        m = np.zeros((H, W), np.uint8)
        cv2.fillConvexPoly(m, pc.astype(np.int32), 255)
        return m

    ident = np.array([[1, 0, 0], [0, 1, 0]], np.float64)
    m0 = roi_mask(ident) & ((alphas[0] > 0.5).astype(np.uint8) * 255)
    cur = detect(grays[0], m0)
    ref = cur.copy()
    if len(cur) < 8:
        print("  ! too few features in head box, track = identity", file=sys.stderr)
        return [ident] * n
    Ms = [ident]
    M = ident
    seq = list(range(1, n)) + [0]  # last step closes the loop back to frame 0
    closing = None
    prev_i = 0
    for step, i in enumerate(seq):
        nxt, good = lk(grays[prev_i], grays[i], cur)
        if good.sum() >= 6:
            Mn, inl = cv2.estimateAffinePartial2D(ref[good], nxt[good], method=cv2.RANSAC,
                                                  ransacReprojThreshold=2.0, maxIters=2000)
            if Mn is not None and inl is not None and inl.sum() >= 6:
                M = Mn
                keep = np.zeros(len(cur), bool)
                keep[np.where(good)[0][inl.reshape(-1) == 1]] = True
                cur, ref = nxt[keep], ref[keep]
            else:
                cur, ref = nxt[good], ref[good]
        if step == n - 1:
            closing = M
            break
        if len(cur) < 40:  # re-seed in the moved head box, map back to frame 0
            mask = roi_mask(M) & ((alphas[i] > 0.5).astype(np.uint8) * 255)
            new = detect(grays[i], mask)
            if len(new):
                Minv = cv2.invertAffineTransform(M)
                new_ref = (new.reshape(-1, 2) @ Minv[:, :2].T + Minv[:, 2]).reshape(-1, 1, 2).astype(np.float32)
                cur = np.concatenate([cur, new]).astype(np.float32)
                ref = np.concatenate([ref, new_ref]).astype(np.float32)
        Ms.append(M.copy())
        prev_i = i

    P = np.array([params_from_M(m) for m in Ms])
    if closing is not None and n > 1:
        drift = params_from_M(closing)  # should be identity (all zeros)
        drift[1] = (drift[1] + math.pi) % (2 * math.pi) - math.pi
        P -= np.outer(np.arange(n) / n, drift)
    # circular smoothing, window 3
    if n >= 3:
        P = (np.roll(P, 1, 0) + 2 * P + np.roll(P, -1, 0)) / 4.0
    return [M_from_params(p) for p in P]


# ---------------------------------------------------------------- main

def parse_clips(items):
    clips = []
    for it in items:
        if "=" in it:
            state, path = it.split("=", 1)
        else:
            path = it
            state = Path(it).stem
        clips.append((state, Path(path)))
    return clips


def parse_polys(s):
    return [[float(v) for v in e.split(",")] for e in s.split(";") if e.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clips", nargs="+", help="state=path.mp4 (or path, state = file name)")
    ap.add_argument("--pet", required=True, help="pet id, e.g. cat_black")
    ap.add_argument("--out", default="assets/pets")
    ap.add_argument("--fps", type=float, default=12)
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--quality", type=int, default=85)
    ap.add_argument("--max-seconds", type=float, default=None)
    ap.add_argument("--pad", type=float, default=0.06, help="padding around the pet")
    ap.add_argument("--align", choices=["bottom", "center"], default="bottom",
                    help="bottom = feet on one line for all pets")
    ap.add_argument("--crop", help="x,y,side in video pixels: fixed crop instead of the bounding box")
    ap.add_argument("--key", choices=["green", "blue"], default="green")
    ap.add_argument("--matte", choices=["chroma", "rembg", "plate"], default="chroma",
                    help="rembg = BiRefNet, slower, use if the pet has green details")
    ap.add_argument("--key-lo", type=float, default=0.18)
    ap.add_argument("--key-hi", type=float, default=0.45)
    ap.add_argument("--recolor-lab", action="store_true", help="recolor only mid-tone fur in Lab; eyes, mouth, dark parts, white markings keep colours (raccoon)")
    ap.add_argument("--soften", type=float, default=0, help="blur alpha by sigma px (anti-alias the edge)")
    ap.add_argument("--choke", type=int, default=0, help="erode alpha by N px (light rim)")
    ap.add_argument("--recolor-white", action="store_true", help="recolor: white markings get the palette too (raccoon)")
    ap.add_argument("--fill-holes", action="store_true", help="opaque interior (muted backdrop + low --key-lo)")
    ap.add_argument("--head", help="x,y,w,h of the head on frame 0, normalised 0..1 in OUTPUT frame")
    ap.add_argument("--head-px", help="x,y,w,h of the head in video pixels (1920x1080, unscaled clip)")
    ap.add_argument("--pick-head", action="store_true", help="select head box with the mouse")
    ap.add_argument("--no-drop-last", action="store_true",
                    help="keep last frame even if it duplicates the first")
    ap.add_argument("--recolor", help="repaint fur: " + ", ".join(PALETTES) +
                    " or custom '#rrggbb@0,#rrggbb@0.5,#rrggbb@1'")
    ap.add_argument("--chroma-max", type=float, default=0.4,
                    help="recolor: max colourfulness of fur near the fur hue (raise if fur patches stay)")
    ap.add_argument("--eyes", help="recolor: eye outlines on frame 0, normalised in the OUTPUT frame, "
                    "'x1,y1,x2,y2,...;...'. Only a search zone, the eyes are found on every frame")
    ap.add_argument("--eyes-px", help="recolor: eye outlines in video pixels (1920x1080, unscaled clip)")
    ap.add_argument("--pick-eyes", action="store_true", help="click eye outlines with the mouse")
    ap.add_argument("--hue-tol", type=float, default=45.0,
                    help="recolor: degrees around the fur hue that count as fur")
    ap.add_argument("--cut-thr", type=float, default=4.0,
                    help="max mean pixel diff to frame 0 for a switch point (0..255)")
    ap.add_argument("--preview", action="store_true", help="write preview_<state>.mp4 with the track")
    ap.add_argument("--sam", nargs="?", const="auto", default=None,
                    help="recolor: eye masks with SAM 2.1 (value: weights file, default sam2.1_t.pt next to this "
                         "script). Masks are cached in <video folder>/eyes/ and reused without torch")
    ap.add_argument("--qa", action="store_true",
                    help="recolor: write qa_<state>.txt (spots per frame) and qa_<state>.jpg (worst frames)")
    args = ap.parse_args()

    clips = parse_clips(args.clips)
    global NO_KEEP_WHITE
    NO_KEEP_WHITE = args.recolor_white
    # clip made from base_16x9_jump.png (pet scaled by k around the bottom centre of the
    # frame): file name happy@0.75.mp4; frames are scaled back so all states line up
    SCALE, _c = {}, []
    for state, path in clips:
        if "@" in path.stem:
            k = float(path.stem.split("@", 1)[1])
            state = state.split("@", 1)[0]
            SCALE[state] = k
        _c.append((state, path))
    clips = _c
    out_dir = Path(args.out) / args.pet
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "pet.json"
    old = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    matte = RembgMatte() if args.matte == "rembg" else None
    PL = {}
    recolor_spec = args.recolor

    def key_frame(bgr):
        plate = PL.get("cur")
        if args.matte == "plate":
            a = diff_alpha(bgr, plate)
            # contact shadows on the floor: darker but still green (Lab a clearly negative)
            ga = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)[..., 1].astype(np.float32) - 128
            a *= 1 - np.clip((-ga - 7) / 6, 0, 1)
            a[a < 0.06] = 0
        else:
            a = matte(bgr) if matte else chroma_alpha(bgr, args.key, args.key_lo, args.key_hi)
        a = clean_alpha(a)
        if args.fill_holes:
            a0 = a
            a = fill_holes(a)
            if args.matte == "plate":  # a filled bay that is plain backdrop green stays transparent
                a = np.where((a0 < 0.5) & (ga < -20), a0, a)
        if args.choke:
            a = cv2.erode(a, np.ones((2 * args.choke + 1,) * 2, np.uint8))
        if not matte:
            bgr, a = refine_matte(bgr, a, plate=plate)
        if args.soften:
            a = cv2.GaussianBlur(a, (0, 0), args.soften)
        return despill(bgr, a, args.key), a

    if args.crop:
        box = tuple(int(round(float(v))) for v in args.crop.split(","))
        print(f"[{args.pet}] crop (fixed): {box}")
    else:
        # pass 1: shared crop over all clips of this pet
        print(f"[{args.pet}] pass 1: bounding box")
        x0 = y0 = 10 ** 9
        x1 = y1 = -1
        for state, path in clips:
            if args.matte == "plate":
                PL["cur"] = make_plate(str(path))
            for bgr in iter_sampled(path, args.fps, args.max_seconds):
                _, a = key_frame(bgr)
                ys, xs = np.where(a > 0.5)
                if len(xs):
                    k = SCALE.get(state, 1.0)
                    H_, W_ = a.shape
                    fx = lambda v: W_ / 2 + (v - W_ / 2) / k
                    fy = lambda v: H_ + (v - H_) / k
                    x0, y0 = min(x0, fx(xs.min())), min(y0, fy(ys.min()))
                    x1, y1 = max(x1, fx(xs.max() + 1)), max(y1, fy(ys.max() + 1))
        if x1 < 0:
            sys.exit("pet not found in any frame: check the backdrop colour / --key-lo --key-hi")
        box = square_box(x0, y0, x1, y1, args.pad, args.align)
        print(f"[{args.pet}] crop: {box}")
    bx, by, bs = box

    def px2norm(vals):
        return [(v - (bx if i % 2 == 0 else by)) / bs for i, v in enumerate(vals)]

    eyes = None
    if args.eyes_px:
        eyes = [px2norm(e) for e in parse_polys(args.eyes_px)]
    elif args.eyes:
        eyes = parse_polys(args.eyes)
    elif not args.pick_eyes and "eyes_px" in old:
        eyes = [px2norm(e) for e in old["eyes_px"]]
    elif not args.pick_eyes and "eyes" in old and old.get("crop") == list(box):
        eyes = old["eyes"]

    head = None
    if args.head_px:
        hv = [float(v) for v in args.head_px.split(",")]
        head = [(hv[0] - bx) / bs, (hv[1] - by) / bs, hv[2] / bs, hv[3] / bs]
    elif args.head:
        head = [float(v) for v in args.head.split(",")]
    elif not args.pick_head and "head_px" in old:
        hv = old["head_px"]
        head = [(hv[0] - bx) / bs, (hv[1] - by) / bs, hv[2] / bs, hv[3] / bs]
    elif not args.pick_head and "head" in old and old.get("crop") == list(box):
        head = old["head"]

    result = {"pet": args.pet, "size": args.size, "fps": args.fps,
              "crop": list(map(int, box)), "clips": dict(old.get("clips", {}))}
    TRACK = args.size * 2 if args.size < 512 else args.size  # tracking resolution

    for ci, (state, path) in enumerate(clips):
        print(f"[{args.pet}] {state}: keying")
        if args.matte == "plate":
            PL["cur"] = make_plate(str(path))
        frames = []
        for bgr in iter_sampled(path, args.fps, args.max_seconds):
            fg, a = key_frame(bgr)
            fr = crop_rgba(fg, a, box, args.size, SCALE.get(state, 1.0))
            frames.append(fr)
        if not frames:
            print(f"  ! no frames in {path}", file=sys.stderr)
            continue
        if not args.no_drop_last and len(frames) > 8:
            # loop point: Veo does not always land exactly on the end frame (the tail swings on
            # past it); the clip is cut at the frame of its last 15% that looks most like frame 0,
            # that frame itself is dropped (it repeats frame 0, a stall on loop)
            g0 = over_gray(frames[0]).astype(np.int16)
            start = max(1, int(len(frames) * 0.85))
            ds = [float(np.abs(over_gray(frames[i]).astype(np.int16) - g0).mean()) for i in range(start, len(frames))]
            k = start + int(np.argmin(ds))
            print(f"  loop cut at frame {k} of {len(frames)} (diff to frame 0: {min(ds):.2f})")
            frames = frames[:k]

        if head is None and args.pick_head:
            view = cv2.resize(over_gray(frames[0]), (args.size, args.size))
            r = cv2.selectROI(f"{args.pet}: select HEAD, Enter to confirm", view, False, False)
            cv2.destroyAllWindows()
            if r[2] == 0:
                sys.exit("no head box selected")
            head = [r[0] / args.size, r[1] / args.size, r[2] / args.size, r[3] / args.size]
        track = None
        if head is not None:
            print(f"[{args.pet}] {state}: tracking head")
            grays = [cv2.cvtColor(cv2.resize(over_gray(f), (TRACK, TRACK)), cv2.COLOR_BGR2GRAY) for f in frames]
            alphas = [cv2.resize(f[..., 3], (TRACK, TRACK)).astype(np.float32) / 255 for f in frames]
            head_px = [int(round(v * TRACK)) for v in head]
            Ms = track_head(grays, alphas, head_px)
            track = [[round(M[0, 0], 5), round(M[1, 0], 5), round(M[0, 2] / TRACK, 5), round(M[1, 2] / TRACK, 5)]
                     for M in Ms]

        if eyes is None and args.pick_eyes:
            view = cv2.resize(over_gray(frames[0]), (1024, 1024), interpolation=cv2.INTER_CUBIC)
            polys = pick_polygons(view, f"{args.pet}: click around EACH EYE, Enter after each eye, Esc to finish")
            eyes = [[v / 1024.0 for pt in pl for v in pt] for pl in polys]
        qa_rows, qa_hulls = [], []
        emasks = None
        if recolor_spec and eyes and args.sam:
            cache = path.parent / "eyes" / f"{path.stem}_{args.size}_{args.fps:g}_{bx}_{by}_{bs}.npz"
            if cache.exists():
                emasks = np.unpackbits(np.load(cache)["m"], axis=-1)[..., :args.size]
                if len(emasks) != len(frames):
                    emasks = None
            if emasks is None:
                try:
                    wts = Path(__file__).resolve().parent / "sam2.1_t.pt" if args.sam == "auto" else Path(args.sam)
                    print(f"[{args.pet}] {state}: SAM eye masks")
                    emasks = sam_eye_masks(frames, eyes, track, str(wts))
                    cache.parent.mkdir(exist_ok=True)
                    np.savez_compressed(cache, m=np.packbits(emasks, axis=-1))
                except Exception as ex:  # no torch / sam2 / weights: colour eye finder
                    print(f"  ! SAM unavailable ({type(ex).__name__}: {ex}); colour eye finder is used", file=sys.stderr)
                    emasks = None
        if recolor_spec:
            recolor = Recolor(recolor_spec, args.chroma_max, args.hue_tol)  # fresh per clip: same tones
            if args.recolor_lab:
                recolor = RecolorLab(recolor_spec)
            out_frames = []
            for i, f in enumerate(frames):
                o = recolor(f) if args.recolor_lab else recolor(f, eyes, track[i] if track else None, emasks[i] if emasks is not None else None)
                out_frames.append(o)
                if args.qa:
                    hulls = recolor.last[2] if recolor.last else np.zeros(f.shape[:2], np.uint8)
                    info = recolor.last[3] if recolor.last else []
                    qa_rows.append((i, qa_spots(o, hulls, recolor_spec, args.size), info))
                    qa_hulls.append(hulls)
            frames = out_frames

        # cut points: frames that look like the base pose (frame 0), the app may
        # switch to another clip there without a visible jump
        small = [cv2.resize(over_gray(f), (128, 128), interpolation=cv2.INTER_AREA).astype(np.int16) for f in frames]
        diffs = [float(np.abs(s - small[0]).mean()) for s in small]
        cuts = [0] + [i for i in range(1, len(frames)) if diffs[i] < args.cut_thr
                      and diffs[i] <= diffs[i - 1] and (i + 1 >= len(frames) or diffs[i] <= diffs[i + 1])]
        print(f"  cut points: {cuts}")

        # write animated webp
        pil = [Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGRA2RGBA)) for f in frames]
        dur = int(round(1000 / args.fps))
        webp = out_dir / f"{state}.webp"
        pil[0].save(webp, save_all=True, append_images=pil[1:], duration=dur, loop=0,
                    quality=args.quality, method=4, lossless=False)
        pil[0].save(out_dir / f"{state}_poster.png", optimize=True)
        result["clips"][state] = {"file": webp.name, "poster": f"{state}_poster.png",
                                  "frameCount": len(frames), "frameMs": dur, "cuts": cuts, "track": track}
        print(f"  -> {webp} ({len(frames)} frames, {webp.stat().st_size / 1e6:.2f} MB)")

        if qa_rows:
            lines = [f"{i}\tspots={len(sp)}\tarea={sum(s[2] for s in sp)}\teyes={info}\t"
                     + " ".join(f"({x},{y},{a})" for x, y, a in sp) for i, sp, info in qa_rows]
            (out_dir / f"qa_{state}.txt").write_text("\n".join(lines) + "\n")
            bad = [r for r in qa_rows if r[1]]
            tot = sum(len(r[1]) for r in qa_rows)
            print(f"  QA: {len(bad)} of {len(qa_rows)} frames with spots ({tot} spots)")
            # sheet: frames with spots first, then blink/squint frames (least visible eye),
            # face zoomed around the head box, spots circled, found eyes outlined in green
            order = [r[0] for r in sorted(bad, key=lambda r: -sum(s[2] for s in r[1]))][:6]
            eye_area = [sum(abs(v) for v in r[2]) if r[2] else 0.0 for r in qa_rows]
            for i in np.argsort(eye_area):
                if len(order) >= 6:
                    break
                if all(abs(int(i) - j) > 2 for j in order):
                    order.append(int(i))
            tiles = []
            for i in sorted(order):
                img = over_gray(frames[i], 200)
                cs, _ = cv2.findContours(qa_hulls[i], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                cv2.drawContours(img, cs, -1, (0, 200, 0), 1)
                for x, y, a in qa_rows[i][1]:
                    cv2.circle(img, (x, y), int(6 + math.sqrt(a)), (0, 0, 255), 2)
                if head is not None and track is not None:
                    a_, b_, tx, ty = track[i]
                    hx, hy, hw, hh = head
                    cx, cy = hx + hw / 2, hy + hh * 0.6
                    cx, cy = (a_ * cx - b_ * cy + tx) * args.size, (b_ * cx + a_ * cy + ty) * args.size
                    half = int(hw * args.size * 0.55)
                    x0, y0 = int(max(0, cx - half)), int(max(0, cy - half * 0.6))
                    img = img[y0:y0 + int(1.2 * half), x0:x0 + 2 * half]
                img = cv2.resize(img, (480, 288))
                cv2.putText(img, str(i), (8, 28), 0, 0.9, (0, 0, 255), 2)
                tiles.append(img)
            while len(tiles) < 6:
                tiles.append(np.full((288, 480, 3), 255, np.uint8))
            cv2.imwrite(str(out_dir / f"qa_{state}.jpg"),
                        np.vstack([np.hstack(tiles[:3]), np.hstack(tiles[3:])]), [cv2.IMWRITE_JPEG_QUALITY, 85])

        if args.preview and track is not None:
            prev_path = out_dir / f"preview_{state}.mp4"
            vw = cv2.VideoWriter(str(prev_path), cv2.VideoWriter_fourcc(*"mp4v"), args.fps, (args.size, args.size))
            bg = checker(args.size)
            hx, hy, hw, hh = [v * args.size for v in head]
            corners = np.array([[hx, hy], [hx + hw, hy], [hx + hw, hy + hh], [hx, hy + hh]])
            for f, (a, b, tx, ty) in zip(frames, track):
                al = f[..., 3:4].astype(np.float32) / 255
                img = (f[..., :3] * al + bg * (1 - al)).astype(np.uint8)
                R = np.array([[a, -b], [b, a]])
                pc = corners @ R.T + np.array([tx, ty]) * args.size
                cv2.polylines(img, [pc.astype(np.int32)], True, (0, 0, 255), 2)
                vw.write(img)
            vw.release()
            print(f"  -> {prev_path}")

    if head is not None:
        result["head"] = [round(v, 4) for v in head]
        result["head_px"] = [round(v, 1) for v in [head[0] * bs + bx, head[1] * bs + by, head[2] * bs, head[3] * bs]]
    if eyes:
        result["eyes"] = [[round(v, 4) for v in e] for e in eyes]
        result["eyes_px"] = [[round(v * bs + (bx if i % 2 == 0 else by), 1) for i, v in enumerate(e)] for e in eyes]
    manifest_path.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    print(f"[{args.pet}] manifest -> {manifest_path}")


if __name__ == "__main__":
    main()
