# PWA shell: offline banner and disabled input

Status: ready-for-human (implemented on saem/hangeul-context-reader; owner review, merge and deploy; the phone check is ticket 8)

Ticket 6 of the spec's §10. See spec §6 (first two bullets) and D10. Blocked by: none (tickets 4 and 5 are done).

## What exists already

Most of the installable shell came with `.scratch/ani-companion/issues/01-pwa-installable.md`:

- `src/app/manifest.ts` (served as `/manifest.webmanifest`, not a file in `public/` as the spec says): name
  "Jeannie", `display: standalone`, portrait, the HUD's theme colour, three icons in `public/icons/`.
- `public/sw.js` (`VERSION` "v3"): `/api/*` network-only and never cached; avatar clips and icons cache-first;
  `/_next/static` stale-while-revalidate; page navigations network-first with the `/` shell cached; cross-origin
  requests untouched; `activate` deletes only caches whose name starts with `jeannie-`, so a transformers.js model
  cache (ticket 7) survives.
- `src/components/ServiceWorkerRegister.tsx` (production only), mounted in `src/app/layout.tsx`.

## What is missing

1. **Reachability.** A hook (e.g. `src/hooks/useOnlineStatus.ts`): `navigator.onLine` plus the `online` / `offline`
   events, plus API reachability (an `ApiRequestError` with status 0 from `src/lib/client/api.ts` means unreachable;
   re-probe `GET /api/status` until it answers).
2. **Banner.** "Offline: Jeannie needs a connection" (and the Korean line), `role="status"`, on the HUD
   (`src/app/page.tsx`) and on the phone's `AvatarScreen`. No offline answers (D10): the device copy of ticket 7 is
   for speed while online, not for answering offline.
3. **Disabled input while offline.** Every send goes through `chat.send` in `page.tsx` (composer, quick commands,
   IoT tiles, voice), so guard it there; `ChatComposer` needs a `disabled` prop (textarea and SEND button, with the
   offline line as the placeholder), `AvatarScreen` an `offline` prop for the hold-to-talk button.
4. **No data in the service worker.** Keep `/api/*` network-only, and assert it for `/api/hangeul/*` in
   `tests/pwa.test.ts` (which evaluates `sw.js` in `node:vm`). Bump `VERSION` if `sw.js` changes.

## What was built

- `src/lib/client/reachability.ts` (pure): the offline state (`browserOnline`, `apiReachable`), its reducer, which
  errors mean "unreachable" (status 0 with `network_error`: fetch itself threw; a timeout is not one, since a long
  answer can time out on a working line), the re-probe delay (2, 4, 8, 16 s, then every 30 s) and the banner's two
  lines.
- `src/lib/client/api.ts`: every request reports whether it reached the server (`onReachability`); any HTTP answer,
  even an error, counts as reached. A reply stream that breaks mid-way counts as unreachable.
- `src/hooks/useOnlineStatus.ts`: `navigator.onLine`, the `online` / `offline` events and those reports; while the
  browser says online but the API did not answer, it re-probes `GET /api/status` until it does.
- `src/components/OfflineBanner.tsx`: "Offline: Jeannie needs a connection" / "오프라인: 지니는 인터넷 연결이 필요해요",
  in a `role="status"` live region that is always mounted (so it is announced), fixed at the top of both views,
  dark on the HUD, light on the avatar screen.
- Disabled input: `page.tsx` has one guarded `send` for the composer, the quick commands, the IoT tiles and voice
  (nothing is sent while offline). `ChatComposer` takes `disabled` / `disabledText` (text box, camera, attach, mic
  and SEND off, the offline line as the placeholder; STOP still works, and a mic already open can still be closed),
  `ChatTerminal` an `offline` prop (also for the quick-command chips), `AvatarScreen` an `offline` prop
  (hold-to-talk off, labelled with the offline line).
- `public/sw.js` `VERSION` "v4": `putInCache` refuses any `/api/` URL whatever strategy asks, and a navigation to an
  `/api/` URL is not handled (no shell fallback for it). Student data lives only in IndexedDB (ticket 7).

## Decisions

1. The manifest stays `src/app/manifest.ts`, which Next serves at `/manifest.webmanifest`: a
   `public/manifest.webmanifest` would clash with that route. Its theme colour is the avatar screen's backdrop
   (`#dbc7c7`, what a phone opens on); `layout.tsx` gives the dark HUD `#0A050A` on other screens.
2. There are no offline answers (D10), not even from the device copy.

## Tests

`tests/pwa.test.ts`: every `/api/hangeul/*` path is network-only; `fetch` events for the snapshot, changes, runs,
data status, ask and chat routes (and a navigation to the snapshot URL) are never answered or cached by the service
worker, against a recording Cache Storage and a network that returns synthetic student JSON; `putInCache` refuses
`/api/` URLs but still stores the shell and icons; the shell is still cached on a navigation to `/`. The reachability
reducer, the "unreachable" rule, the re-probe delays and the banner lines. The hook and the banner are React code with
no DOM test setup in the repo, so their logic lives in `reachability.ts`.

## Comments

- 1 Oct 2026: built with ticket 7. `npx vitest run` 1169 passed and 8 skipped; `tsc`, `npm run lint` and
  `npm run build` are clean. The phone check (install, airplane mode shows the banner) is ticket 8, step 2.
- 1 Oct 2026: checked in the desktop app's browser pane against `next start` (no keys, no data). An `offline` event
  shows the banner on the HUD (dark) and on the phone's avatar screen (light); the text box, SEND and hold-to-talk
  are disabled with the offline line; `online` restores them. With the server stopped, a send shows the banner and
  "Uplink unreachable"; once the server was back, the re-probe of `/api/status` cleared it by itself. The pane
  refuses service-worker registration ("unknown error when fetching the script") although `/sw.js` answers 200 as
  JavaScript, so the worker's rules rest on `tests/pwa.test.ts` and the phone check.
- 1 Oct 2026 (review fixes): offline, the smart-home tiles, the thermostat -/+ and the Hangeul Data panel's DAILY
  REPORT were still enabled; a tap flipped the tile while `send()` dropped the command. They are now disabled with
  the offline line as their title, a tile flips only when its command was sent (`sendToggle`), and a debounced
  thermostat setting that finds the HUD offline goes back to the last one sent. The wiring is now tested
  (`tests/offline-controls.test.ts`): `api.ts` with a stubbed fetch (a thrown fetch reports unreachable, any HTTP
  answer reachable, a timeout or a user abort nothing), the send guard (`sendUnlessOffline`), the composer rule
  (`canSendMessage`) and the re-probe loop (`startProbeLoop`) as pure helpers, and the banner, composer, tiles and
  DAILY REPORT rendered with `react-dom/server` (no new dependency; `vitest.config.mts` compiles the components' JSX).
