# Jeannie

## Avatar

**NEUTRAL** — the canonical neutral frame: standing centred, hands clasped behind the back, calm eye
contact, faint composed smile. Higgsfield media `ecc09fc0-847a-4ca4-b2eb-a1a4a0835fff`
(= `assets/avatar/source/fullbody.png`). Immutable; see ADR 0001. Also written **N**.

**Clip** — one pre-rendered 9:16 video of the avatar. Classes:
- **loop** — gated as a loop (closes on itself): idle, sway, listening, speaking. The app loops idle
  (shown before the greeting and under listening) and speaking (`talking` in code) while their state
  lasts, and plays one cycle of sway as a step of the idle sequence.
- **one-shot** (N→N) — plays once and hands back to idle: every emote.
- **entry** (—→N), **exit** (N→—), **variant-end** (N→N(B)): outfit_change, environment_change.

**Idle sequence** — what she plays while idle, back-to-back and non-stop: spin → playful →
shyness → heartbeat → sway, then again. Each step hands over on its last (NEUTRAL) frame. Talking or
the mic drops the current step at once; a reply emote waits for the step to end.

**Carrier** — the gross body motion that makes an emote read at phone size (lean, weight shift, nod,
shoulders). Faces alone do not read under a double pin. A carrier must never bring a hand to the
torso: that makes Kling re-render the clothing.

**Accept gate** — three parts, all mandatory. `scripts/avatar-clips/gate.py` measures 1 and 2 and
writes the evidence for 3.

1. **Closure**, measured against NEUTRAL, not the clip's own first frame:

   | Class | Measure |
   |---|---|
   | loop | PSNR(own f0, own last) ≥ 35 dB, and f0 vs NEUTRAL ≥ 35 dB |
   | one-shot | PSNR(NEUTRAL, f0) and PSNR(NEUTRAL, last) ≥ 35 dB |
   | entry | PSNR(NEUTRAL, last) ≥ 35 dB only |
   | exit | PSNR(NEUTRAL, f0) ≥ 35 dB only; its end is free |
   | variant-end | f0 vs NEUTRAL; last vs N(B) or N(scene B) |

2. **Expression floor** (one-shots only; loops are exempt): the minimum PSNR against NEUTRAL anywhere
   in the clip is ≤ 34 dB. Above it, nothing visible happened.
3. **Visual review**: the frame at the minimum-PSNR position **and** a whole-body contact sheet of
   every 18th frame. Check every limb, not just the gesturing one: hand geometry and finger count,
   wardrobe integrity, pose overshoot, and whether the clip reads as the emotion it is named for.

Every rejection in this project passed Parts 1 and 2 and was caught by Part 3. A clip that passes
the numbers is not a clip that ships.

_Avoid_: judging closure against a clip's own first frame (one-shots), playback-only review.

**Encode** — what the live app plays: 720×1280, 24 fps, H.264 high, CRF 23, yuv420p, no audio,
`+faststart`. Kling renders at 24 fps; never convert to 30.
