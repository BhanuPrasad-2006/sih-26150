"""
personas.py — procedurally drawn cartoon people for the test pack.

These are NOT photographs and NOT real people: they are simple shaded avatars drawn with OpenCV, so nothing here
identifies anyone and no photo is copied from anywhere. They exist so a face detector has faces to find and a
face-search feature has a "reference photo" to look for. Because they are avatars, results only prove that the
plumbing works (detect -> embed -> search); they say nothing about accuracy on real people. To test with real people,
pass your own consented photos to make_test_pack.py (--photo-a / --photo-b).
"""

from __future__ import annotations

import random

import cv2
import numpy as np

_SKINS = [((150, 185, 225), (110, 140, 185)), ((110, 150, 200), (80, 110, 160)),
          ((70, 100, 150), (50, 75, 115)), ((170, 200, 235), (130, 160, 200))]
_HAIRS = [(20, 25, 40), (60, 90, 130), (30, 60, 110), (200, 200, 205), (15, 15, 15), (40, 80, 170)]
_BGS = [(200, 190, 180), (185, 200, 190), (170, 175, 200), (210, 205, 190)]

# Seeds chosen by search: distinct to the SFace model (cosine well under its 0.363 match threshold) and still
# recognisable after shrinking, blur and JPEG compression. make_test_pack.py re-checks this every time it runs.
PERSON_SEEDS = {"A": 2, "B": 266}


def params_for(seed: int) -> dict:
    rng = random.Random(seed)
    skin, dark = rng.choice(_SKINS)
    return dict(bg=rng.choice(_BGS), shirt=tuple(rng.randrange(30, 200) for _ in range(3)), neck=skin, skin=skin,
                skin_dark=dark, hair=rng.choice(_HAIRS), hair_style=rng.choice(["short", "long"]),
                face_w=rng.uniform(0.19, 0.27), face_h=rng.uniform(0.28, 0.36), eye_gap=rng.uniform(0.38, 0.6),
                eye_h=rng.uniform(0.02, 0.045), brow=(20, 25, 35), brow_w=rng.choice([2, 3, 5, 7]),
                brow_tilt=rng.choice([-3, -1, 0, 1, 3]), iris=tuple(rng.randrange(20, 160) for _ in range(3)),
                nose_w=rng.uniform(0.025, 0.07), mouth_w=rng.uniform(0.045, 0.1), lip=(80, 90, 180),
                smile=rng.random() < 0.7, beard=rng.random() < 0.3, glasses=rng.random() < 0.4)


def portrait(p: dict, size: int = 300) -> np.ndarray:
    """A shaded, front-facing head-and-shoulders avatar on a plain background (BGR uint8)."""
    S = size
    img = np.full((S, S, 3), p["bg"], np.uint8)
    cx, cy = S // 2, int(S * 0.46)
    cv2.ellipse(img, (cx, S + 10), (int(S * 0.46), int(S * 0.32)), 0, 180, 360, p["shirt"], -1, cv2.LINE_AA)
    cv2.rectangle(img, (cx - int(S * 0.08), int(S * 0.62)), (cx + int(S * 0.08), int(S * 0.80)), p["neck"], -1)
    if p["hair_style"] == "long":
        cv2.ellipse(img, (cx, cy + 10), (int(S * 0.27), int(S * 0.36)), 0, 0, 360, p["hair"], -1, cv2.LINE_AA)
    fw, fh = int(S * p["face_w"]), int(S * p["face_h"])
    mask = np.zeros((S, S), np.uint8)
    cv2.ellipse(mask, (cx, cy), (fw, fh), 0, 0, 360, 255, -1, cv2.LINE_AA)
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    shade = np.clip(1.0 - 0.28 * (((xx - (cx - fw * 0.25)) / fw) ** 2 + ((yy - (cy - fh * 0.2)) / fh) ** 2), 0.62, 1.05)
    face = (np.array(p["skin"], np.float32)[None, None, :] * shade[:, :, None]).clip(0, 255)
    m3 = mask[:, :, None] / 255.0
    img = (img * (1 - m3) + face * m3).astype(np.uint8)
    for sx in (-1, 1):
        cv2.ellipse(img, (cx + sx * (fw - 2), cy + 6), (int(S * 0.035), int(S * 0.06)), 0, 0, 360, p["skin_dark"], -1, cv2.LINE_AA)
    hair = np.zeros((S, S), np.uint8)
    cv2.ellipse(hair, (cx, cy - int(fh * 0.18)), (fw + 6, int(fh * 0.95)), 0, 180, 360, 255, -1, cv2.LINE_AA)
    cv2.ellipse(hair, (cx, cy + int(fh * 0.05)), (int(fw * 0.86), int(fh * 0.72)), 0, 0, 360, 0, -1, cv2.LINE_AA)
    h3 = hair[:, :, None] / 255.0
    img = (img * (1 - h3) + np.array(p["hair"], np.float32)[None, None, :] * h3).astype(np.uint8)
    ex, ey = int(fw * p["eye_gap"]), cy - int(fh * 0.14)
    for sx in (-1, 1):
        x0 = cx + sx * ex
        cv2.line(img, (x0 - int(S * 0.055), ey - int(S * 0.055) + p["brow_tilt"] * sx),
                 (x0 + int(S * 0.055), ey - int(S * 0.055) - p["brow_tilt"] * sx), p["brow"], p["brow_w"], cv2.LINE_AA)
    for sx in (-1, 1):
        x0 = cx + sx * ex
        cv2.ellipse(img, (x0, ey), (int(S * 0.05), int(S * p["eye_h"])), 0, 0, 360, (245, 245, 245), -1, cv2.LINE_AA)
        cv2.circle(img, (x0, ey), int(S * 0.028), p["iris"], -1, cv2.LINE_AA)
        cv2.circle(img, (x0, ey), int(S * 0.014), (10, 10, 10), -1, cv2.LINE_AA)
        cv2.circle(img, (x0 - 3, ey - 3), 2, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.ellipse(img, (x0, ey), (int(S * 0.05), int(S * p["eye_h"])), 0, 180, 360, p["brow"], 2, cv2.LINE_AA)
    ny = cy + int(fh * 0.12)
    cv2.line(img, (cx, ey + 6), (cx - int(S * 0.012), ny), p["skin_dark"], 3, cv2.LINE_AA)
    cv2.ellipse(img, (cx, ny + 3), (int(S * p["nose_w"]), int(S * 0.02)), 0, 0, 180, p["skin_dark"], 3, cv2.LINE_AA)
    for sx in (-1, 1):
        cv2.circle(img, (cx + sx * int(S * p["nose_w"] * 0.7), ny + 4), 3, (60, 40, 40), -1, cv2.LINE_AA)
    my, mw = cy + int(fh * 0.46), int(S * p["mouth_w"])
    cv2.ellipse(img, (cx, my), (mw, int(S * 0.028)), 0, 0, 180 if p["smile"] else 360, p["lip"], -1, cv2.LINE_AA)
    cv2.ellipse(img, (cx, my - 2), (mw, int(S * 0.012)), 0, 180, 360, p["lip"], -1, cv2.LINE_AA)
    if p.get("beard"):
        b = np.zeros((S, S), np.uint8)
        cv2.ellipse(b, (cx, cy + int(fh * 0.25)), (int(fw * 0.92), int(fh * 0.78)), 0, 10, 170, 255, -1, cv2.LINE_AA)
        cv2.ellipse(b, (cx, cy + int(fh * 0.10)), (int(fw * 0.6), int(fh * 0.5)), 0, 0, 360, 0, -1, cv2.LINE_AA)
        b3 = (cv2.GaussianBlur(b, (5, 5), 0)[:, :, None] / 255.0) * 0.85
        img = (img * (1 - b3) + np.array(p["hair"], np.float32)[None, None, :] * b3).astype(np.uint8)
    if p.get("glasses"):
        for sx in (-1, 1):
            cv2.circle(img, (cx + sx * ex, ey), int(S * 0.075), (30, 30, 30), 3, cv2.LINE_AA)
        cv2.line(img, (cx - ex + int(S * 0.075), ey), (cx + ex - int(S * 0.075), ey), (30, 30, 30), 3, cv2.LINE_AA)
    return cv2.GaussianBlur(img, (3, 3), 0)


def person_portrait(name: str) -> np.ndarray:
    return portrait(params_for(PERSON_SEEDS[name]))


def cutout(img: np.ndarray, bg_bgr: tuple) -> tuple[np.ndarray, np.ndarray]:
    """(bgr, alpha 0..1): the person without the flat portrait background, so they can walk through a scene."""
    diff = np.abs(img.astype(np.int16) - np.array(bg_bgr, np.int16)[None, None, :]).sum(axis=2)
    alpha = (diff > 24).astype(np.uint8) * 255
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    alpha = cv2.GaussianBlur(alpha, (5, 5), 0)
    return img, alpha.astype(np.float32) / 255.0
