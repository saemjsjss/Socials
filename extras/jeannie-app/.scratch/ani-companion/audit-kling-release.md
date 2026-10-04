# Pre-live audit: Kling clip set release (branch `saem/busy-pascal-4ieetx`, 2026-09-29)

Verdict: **no blockers**. Ready for the owner's phone test on the Vercel preview, then a manual merge.

## What was checked

| Check | Result |
|---|---|
| Typecheck, lint, production build | pass |
| Unit tests | 927 pass (7 new: emote rules, Kling ingest, manifest parity, picker gate) |
| Accept gate on all 17 encoded clips in `public/avatar/` | all pass Part 1 (closure 40.7–42.2 dB vs NEUTRAL); one-shots pass Part 2 |
| Phone run, real Google Chrome, Galaxy S24 viewport, simulated 4G | 17/17 emotes play, 0 console errors, 0 failed requests, every one-shot hands back to idle |
| First frame on simulated 4G | 1.9 s, 0.32 MB downloaded before she appears |
| Repeat visit (service worker on) | 0 MB of video from the network |
| Idle loop seam (encoded) | 44.6 dB (old live idle: 36.2 dB, visibly jumps) |
| Code review (standards + spec, two independent reviewers) | findings below |
| Security | small surface: picker is client-only, no data; the only new public config is the deploy name ("preview"/"production"); new scripts run only on a developer machine |

## Findings

### Fixed during the audit
1. **Background loading was not really limited.** Every clip was requested at once. It now loads 2 at a
   time after the essential clips. First frame went from 3.7 s to 1.9 s on simulated 4G.
2. **The QA picker covered her face** when open. It was moved below her face.
3. **Docs drift:** CONTEXT.md now says sway is a loop-class clip that the app plays one cycle of.

### Open: owner decisions or next release
1. **AI emote check not run yet.** The preview is behind Vercel login (302), so this needs the owner.
   Send a few messages on the preview and check that she picks sensible emotes and that no
   `[emote:…]` text shows in chat, voice or Telegram.
2. **The old greeting, air_kiss and nod clips sit slightly off the anchor** (about 33 dB). You may see
   a small shift when she switches to or from them. This was kept by the owner's choice.
3. ~~**"excited" and "excitement" are close names.**~~ Done: `excited` is now `playful` (see below).
4. **First visit downloads each clip twice** when the service worker is not yet active (warm-up plus
   player). This behaviour predates the release. Repeat visits cost nothing.
5. **`?debug=emotes` shows the picker on non-Vercel builds.** It only matters if the app is ever
   hosted outside Vercel.
6. ~~**Lip-sync is still generic.**~~ Partly done: her mouth now rests when her voice pauses (see
   below). It is not word-exact lip-sync.

## Follow-up: jumpy idle on the preview (fixed)
The owner still saw idle jump on the preview.
- **Cause:** the app cut into idle **mid-loop**. The sway variation every 30–60 s and emotes started
  at once. Clips only meet NEUTRAL at their first and last frames, and idle drifts up to 33.6 dB away
  mid-loop. Listening had also become a separate clip, so the mic caused a cut too.
- **Fix:**
  - Emotes and sway now wait for idle's loop point (at most one idle cycle).
  - Voice and mic changes still cut at once, with a 400 ms blend.
  - Listening is idle plus a zoom again.
  - Clip URLs carry `?v=k2`, so a phone with the old cache fetches the new clips on the first open.
- **Measured in real Chrome** (the lowest PSNR across a cut: the smaller it is, the bigger the jump):
  worst cut **35.9 dB before → 41.9 dB after**. An emote now appears 1.5–3.9 s after the tap.
- The legacy greeting on open still cuts at about 35 dB. It is an off-anchor MiniMax clip, kept by the
  owner's choice.

## Follow-up: mouth rests in voice pauses, `excited` renamed to `playful`
- **Mouth rests:**
  - While she talks, the app reads her voice level every frame.
  - After 180 ms of silence, the talking clip runs on to the next frame where her mouth is closed or
    barely parted, and holds there. It plays on 60 ms after her voice returns.
  - The ingest script finds these "rest" frames: 75 of 193 frames, never more than 0.92 s apart.
  - This only works with the server voice, where the level is really measured. With the browser voice
    she talks exactly as before.
- **Rename:** `excited` is now `playful`, so it is no longer confused with `excitement`. A model that
  still writes `[emote:excited]` gets `playful`. Clip URLs moved to `?v=k3`.
- **Measured in real Chrome (QA "voice test": 1.2 s voice / 0.8 s silence, ×4):**

  | Check | Target | Result |
  |---|---|---|
  | Mouth rests in each gap | ≤ 1.0 s | 229–396 ms |
  | Resume after the voice returns | ≤ 150 ms | ~96 ms |
  | Mouth darkness on held frames (closed = 22) | ≤ 40 | 7, 37, 39, 36 |
  | Console errors | 0 | 0 |
- **Jump harness, playful included:** worst cut 41.9 dB, green. The legacy greeting is unchanged at
  35.2 dB.
- **Tests:** 943 pass, including a new voice-gate suite.

## Follow-up: idle is a non-stop sequence
- **Owner's request:** while idle she plays spin → playful → shyness → heartbeat → sway back-to-back,
  then again. One cycle is about 34 s. It starts right after the greeting. The 30–60 s sway variation
  is gone; sway is now the fifth step.
- **Talking or the mic** drops the current step at once. When she is idle again, the sequence resumes
  at the next step.
- **A reply emote without voice** waits for the current step to end (at most 8 s), so the cut stays
  seamless.
- **Measured in real Chrome, 50 s after load:**
  - the order is correct, with no idle clip in between;
  - every clip-to-clip join is 41.9–43.8 dB (invisible);
  - there are 0 console errors;
  - the voice test is unchanged.
- **Known:** the legacy greeting's cuts in and out (35.1 dB) are unchanged and kept by the owner's choice.
  They now hand over to spin instead of idle.

## Release steps for the owner
1. Open the preview on your phone (you are signed in to Vercel).
2. Tap **Emotes (QA)** and play every emote. Tap **voice test** to watch her mouth rest in the pauses.
3. Chat a little to check the AI's emote choice.
4. If happy: GitHub PR → **Ready for review** → **Merge**. Vercel deploys the live site.
5. If anything is wrong after going live: in Vercel, **Promote** the previous deployment. This is
   instant rollback.
