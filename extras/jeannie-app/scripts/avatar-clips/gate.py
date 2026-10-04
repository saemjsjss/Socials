#!/usr/bin/env python3
"""Accept gate for mascot clips (dev-time only). See CONTEXT.md, "Accept gate".

  python3 scripts/avatar-clips/gate.py <class> <clip.mp4> <out_dir> [anchor.png]

class: loop | oneshot | entry | exit
Part 1 (closure) and Part 2 (expression floor, one-shots only) are measured here.
Part 3 (visual review) needs eyes: this writes the peak frame and a whole-body
contact sheet of every 18th frame to out_dir for that review. Passing Parts 1
and 2 never means the clip ships.
Needs numpy and an ffmpeg binary (FFMPEG env var, else `ffmpeg` on PATH, else imageio-ffmpeg).
"""
import json, os, shutil, subprocess, sys
import numpy as np

W, H = 720, 1280
CLOSE_DB, FLOOR_DB, SHEET_STEP = 35.0, 34.0, 18
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
ANCHOR = os.path.join(ROOT, "assets/avatar/source/fullbody.png")  # == Higgsfield media ecc09fc0-847a-4ca4-b2eb-a1a4a0835fff


def ffmpeg():
    exe = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def frames(path):
    out = subprocess.run([ffmpeg(), "-v", "error", "-i", path, "-vf",
                          f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(out, np.uint8).reshape(-1, H, W, 3)


def psnr(a, b):
    mse = ((a.astype(np.float32) - b.astype(np.float32)) ** 2).mean()
    return 99.0 if mse == 0 else float(10 * np.log10(255 ** 2 / mse))


def main():
    cls, clip, out = sys.argv[1:4]
    anchor = frames(sys.argv[4] if len(sys.argv) > 4 else ANCHOR)[0]
    f = frames(clip)
    n = len(f)
    to_n = [psnr(x, anchor) for x in f]
    peak = int(np.argmin(to_n))
    r = {"clip": os.path.basename(clip), "class": cls, "frames": n, "seconds": round(n / 24, 3),
         "f0_vs_anchor": round(to_n[0], 2), "last_vs_anchor": round(to_n[-1], 2),
         "f0_vs_last": round(psnr(f[0], f[-1]), 2), "min_vs_anchor": round(to_n[peak], 2), "peak_frame": peak}
    if cls == "loop":
        p1 = r["f0_vs_last"] >= CLOSE_DB and r["f0_vs_anchor"] >= CLOSE_DB
    elif cls == "entry":
        p1 = r["last_vs_anchor"] >= CLOSE_DB
    elif cls == "exit":
        p1 = r["f0_vs_anchor"] >= CLOSE_DB
    else:
        p1 = r["f0_vs_anchor"] >= CLOSE_DB and r["last_vs_anchor"] >= CLOSE_DB
    r["part1_closure"] = "pass" if p1 else "FAIL"
    r["part2_floor"] = ("pass" if r["min_vs_anchor"] <= FLOOR_DB else "FAIL") if cls == "oneshot" else "exempt"
    r["part3_visual"] = "pending"

    os.makedirs(out, exist_ok=True)
    stem = os.path.splitext(os.path.basename(clip))[0]
    ff = ffmpeg()
    subprocess.run([ff, "-v", "error", "-y", "-i", clip, "-vf", f"select=eq(n\\,{peak})", "-frames:v", "1",
                    os.path.join(out, f"{stem}.peak.png")], check=True)
    idx = list(range(0, n, SHEET_STEP)) + ([n - 1] if (n - 1) % SHEET_STEP else [])
    rows = -(-len(idx) // 5)
    sel = "+".join(f"eq(n\\,{i})" for i in idx)
    subprocess.run([ff, "-v", "error", "-y", "-i", clip, "-vf",
                    f"select='{sel}',scale=360:640,drawtext=text='%{{n}}':x=8:y=8:fontsize=28:fontcolor=white:box=1:boxcolor=black@0.5,tile=5x{rows}",
                    "-frames:v", "1", "-fps_mode", "vfr", os.path.join(out, f"{stem}.sheet.jpg")],
                   check=False, capture_output=True)
    if not os.path.exists(os.path.join(out, f"{stem}.sheet.jpg")):  # drawtext needs a font; fall back to no labels
        subprocess.run([ff, "-v", "error", "-y", "-i", clip, "-vf", f"select='{sel}',scale=360:640,tile=5x{rows}",
                        "-frames:v", "1", "-fps_mode", "vfr", os.path.join(out, f"{stem}.sheet.jpg")], check=True)
    r["sheet_frames"] = idx
    print(json.dumps(r))


if __name__ == "__main__":
    main()
