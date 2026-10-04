# Rebuild the avatar on the Kling clip set (REMINDER — read first when the app rebuild starts)

Status: needs-triage

Waiting on the owner. Do not start until they say the rebuild begins; then remind them of everything
below before touching code.

## Pending, in order

1. **Push decision.** Branch `saem/busy-pascal-4ieetx` holds unpushed commits (clips, ADR 0001,
   CONTEXT.md accept gate, `scripts/avatar-clips/gate.py`). Nothing is live. The owner pushes only on
   their own "push".
2. **Idle fix (no credits).** Live `public/avatar/idle.mp4` is an unpinned early render cut at frame 120
   and dissolved into frame 0: loop seam 36.2 dB, worst in-clip step 31.2 dB, so it visibly jumps.
   Replace with `assets/avatar/kling/01_idle_neutral.mp4` (seam 45.8 dB) with no cut or dissolve.
   Replace the idle-variation `nod` (MiniMax, ~33 dB off-anchor) with an anchored Kling clip
   (`supportive` or `sway`). Consider hard cuts instead of the 150 ms crossfade once all clips are anchored.
   Side-by-side proof: `assets/avatar/kling/qa/idle_live_vs_kling.mp4`.
3. **Lip-sync, step 1 (no credits).**
   - A: gate the talking clip on the TTS audio level (Web Audio analyser): play while voiced, rest
     mouth-closed in pauses.
   - B: use `assets/avatar/kling/23_speaking.mp4` for `talking` instead of the MiniMax clip.
   - Word-exact lip-sync (per-reply lip-sync render, live avatar service, or a 2D rig) is a later,
     paid decision for the owner.
4. **Add the new emotes.** The owner picks the reply-emote list and a "when to use" line for each. Then:
   encode into `public/avatar/` + manifest (do NOT run `npm run avatar:clips` unchanged — it rebuilds
   `public/avatar/` from the old sources); update `EMOTES`/`REPLY_EMOTES`/`EMOTE_DIRECTIVE` in
   `src/lib/emote.ts` and `DEFAULT_CLIPS` in `src/lib/avatar/clips.ts`; map `listening` → listening
   clip, `talking` → speaking; keep old names resolvable; lazy-load non-essential clips (today all clips
   are fetched on mount, ~22 MB with the full set) and bump the `sw.js` cache version; update
   `tests/emote.test.ts` and `tests/avatar.test.ts`.
5. **Verify before live.** typecheck, lint, test, build → run the app and trigger every emote with
   screenshots → test messages for sensible emote choice and no visible tags (app + Telegram) → Vercel
   preview link on the owner's phone → merge to `main` only on the owner's word.

## Clip set status (2026-09-29)

19 accepted in `assets/avatar/kling/` (see `clips.json`): idle, entry, exit, peek, spin, sway, sway_2,
curiosity, shyness, excitement, love, stress, sadness, frustration, concern, supportive, heartbeat,
listening, speaking.
Rejected / missing: air_kiss (hand defect), korean_greeting (attempt 4 kept the waist straight but
moved too little: Part 2 35.85 dB), outfit_change, environment_change (deferred; round-trip design
recommended). ~124.5 credits spent this round.
