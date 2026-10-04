# Spec: Ani-style avatar companion

Status: ready-for-agent

Turn Jeannie into a personal companion in the spirit of Grok's "Ani": on the user's phone the default
screen is a full-body video avatar of Jeannie who greets in Korean on every load, reacts to the
conversation with emotes, and talks by hold-to-talk voice. Desktop keeps the existing neon HUD unchanged.

Decisions below were settled in a grilling session (2026-09-29); numbers refer to that session's questions.

## Character

One consistent adult virtual companion. Identity, face, hairstyle, body, outfit (pink blazer, pink belted
mini skirt, white top, pink hair bow, heart earrings, black platform heels), lighting, background and
camera scale are fixed by the reference frames in `assets/avatar/source/`. Never redesign her.

Personality ("corporate sexy", Q17): calm, intelligent, attentive, elegant, always affectionate and
courteous, observant and obedient, deeply concerned about the user's well-being and business, always
supportive, and asks for clarification whenever a request is unclear. Warm and gently flirtatious, never
explicit. No jealousy, possessiveness or guilt-tripping (Ani's persona is explicitly *not* copied).
No affection meter (Q16): she is always at maximum affection.

Address (Q15): 부장님 in work/business context, 자기야 in affectionate/personal moments. The user's local
time zone is Asia/Dhaka (Q11, already `JEANNIE_TIMEZONE`).

## Rendering (Q1, Q13)

A clip state machine, not a 3D rig. Clips are 720x1280 (9:16) H.264, 24 fps, no audio; each starts and ends
on the shared neutral idle pose so cuts are invisible. On the phone the video fills the viewport height
with `object-fit: cover` (sides cropped ~70px; the plain backdrop hides it). Page background matches the
backdrop colour (sample it from the clip, approx. `#d9cfd2`).

Emotes (Q24) — contract in `src/lib/emote.ts`:

| Emote | Source | Behaviour |
|---|---|---|
| idle | `idle` clip (user supplied) | seamless loop, default |
| listening | idle clip | while the talk button is held; idle plus a subtle CSS focus (slight zoom, soft vignette) |
| talking | generated | loops while TTS audio plays |
| greeting | generated (bow) | on every load, then idle |
| air_kiss | generated | reply emote |
| concern | user supplied | reply emote |
| sadness | user supplied | reply emote |
| nod | generated | reply emote; also used as an idle variation |

Reply emotes play once when the reply's tag is parsed, then hand over to `talking` if speech is playing,
else `idle`. Crossfade ~150 ms between clips using two stacked `<video>` elements; preload all clips.

Clip files live at `public/avatar/<emote>.mp4` with `public/avatar/<emote>.jpg` posters (first frame).
Until the generated clips land, placeholder files built by the clip pipeline keep the app working.

### Clip pipeline (Q19, Q22)

`scripts/avatar-clips/` builds `public/avatar/*` from `assets/avatar/source/*` using HyperFrames
(https://github.com/heygen-com/hyperframes, `npx hyperframes`) plus ffmpeg. Dev-time only; never a runtime
dependency. Idle loop fix: cut the idle source at ~4.8 s (before the hair artifact and eye closing), then
crossfade the final ~0.5 s into the first frame so the loop seam is invisible. Encode web-friendly
(`+faststart`, yuv420p, CRF ~23, keep 720x1280). Placeholders for missing clips are built from the frame
sheets (`greeting-sheet.webp`, `air-kiss-sheet.webp`) and the idle clip.

## Mode switching (Q3, Q4, Q12)

- Avatar mode is the default when `(orientation: portrait) and (min-width: 360px) and (max-width: 480px)
  and (pointer: coarse)` matches. Tuned for Galaxy S24/S25/S26 Ultra (~412 CSS px wide, DPR ~3.5).
  Everything else (desktop) gets the HUD exactly as it is today.
- A manual choice persists per device in localStorage `jeannie.view` = `"avatar" | "hud"`.
- Avatar screen: two floating buttons at the bottom. Left: switch to HUD. Right: hold-to-talk mic (Q7a).
- HUD on a phone: the existing responsive layout plus a floating avatar button to go back.
- Subtitles of her current reply float over the lower third of the avatar.

## Greeting (Q5, Q6)

On every page load (refresh, reopen) she plays `greeting` and says an AI-written Korean greeting based on
the Dhaka time of day, how long the user has been away (client sends `awayMs` from localStorage
`jeannie.lastSeen`), and something recalled from memory. The endpoint returns within ~4 s or falls back to
the existing template greeting. Chrome only (no iOS work). Audio plays straight away in the installed
PWA; if autoplay is blocked, the subtitle shows immediately and the voice plays on first tap.

## Idle behaviour (Q21)

After 30 s of silence (no speech, no input) play a subtle variation (`nod` or a short idle glance), then at
random 30–60 s intervals. After ~3 min of silence she checks in once, in Korean (e.g. asking if the user is
okay or suggesting a break), with `concern`, spoken if voice is on. Reset on any interaction.

## PWA (Q14)

Installable on Android Chrome: `src/app/manifest.ts` (standalone, portrait, theme colour), 192/512 and
maskable icons generated from the character's face, and a minimal service worker (app-shell + avatar clip
cache, network-first for `/api/*`, never cache API responses).

## Tools (Q11, Q20)

The existing `webSearch` tool stays. Add:
- `readUrl`: fetch a page as clean text via Jina Reader (`https://r.jina.ai/<url>`), falling back to our own
  fetch + HTML-to-text. Timeouts, size caps, http(s) only, block private/loopback hosts.
- `currentTime`: current time in any IANA zone or city (default Asia/Dhaka).
- `convertTime`: convert a time between zones.
Tools only run where `supportsTools()` is true, as today.

## Out of scope

Affection meter, outfits, 3D/Live2D, lip-sync, iOS/Safari, explicit sexual content.
