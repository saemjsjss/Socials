# 0001 — The NEUTRAL anchor is immutable

Status: accepted (2026-09-29)

## Decision

Every avatar clip is pinned to one frame, **NEUTRAL**: Higgsfield media
`ecc09fc0-847a-4ca4-b2eb-a1a4a0835fff`, byte-identical to
`assets/avatar/source/fullbody.png` (sha256 `3172b936…19cc`). It is the start **and** end frame of
every clip, except `entry` (end frame only) and `exit` (start frame only). It is never regenerated,
re-cut, re-uploaded or edited.

## Why

- A clip only closes on the pose it started from when its end frame is pinned: start-frame-only
  renders landed 20.9–25.5 dB from their own first frame; pinning both ends lands every clip at
  41.5–43 dB from NEUTRAL, which is what makes hard cuts between independently generated clips
  invisible.
- Every accepted clip inherits NEUTRAL. A second anchor, even a near-copy, invalidates them all.
  Re-cutting was costed at ~110 credits of rework and rejected.
- The wardrobe breakage that motivated a re-cut (a higher neckline) is caused by gestures that touch
  the torso, not by the anchor: the non-torso `concern` test (job `1a633d77`) kept the top intact in
  all 145 frames. Carriers that keep the hands off the torso are the fix.

## Consequences

- Generation: Kling 3.0 std, 9:16, sound off, `start_image` and `end_image` = NEUTRAL.
- A clip is judged against NEUTRAL, not against its own first frame (see CONTEXT.md, Accept gate).
- The pre-anchor sources (`fd3b4f01…` "img 1 start.jpeg", and `7959def3…`, frame 0 of the
  unpinned idle render) are not anchors and are never used as pins.
