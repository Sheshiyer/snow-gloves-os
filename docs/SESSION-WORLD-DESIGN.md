# Session World — playable fleet visualization

Status: design candidate, 2026-09-30. Owner direction: adapt the OpenOrca flat
dashboard concept into a 3D pixel-art mini-game, with walkable interaction in
the spirit of Gather. Original art and layout; no copied Gather assets.

## Experience

A compact Axtech campus contains brand rooms for HeyZack, Ecoled, Kartezzi,
and future mapped brands. The operator moves an avatar with keyboard/touch or
click-to-move. Every session appears as a desk/workstation with a status marker;
approach/select it to open session details, output, artifacts, and allowed actions.
The authoritative session is independent of its scene object and location.

Use genuine 3D depth with an orthographic/isometric camera, low-resolution
textures, crisp nearest-neighbor sampling, pixel characters, and restrained
voxel geometry. Keep labels legible at normal screen size. Final renderer/library
selection follows a benchmark and verified compatibility with the existing web
application; do not assume a complete upstream dashboard fork is necessary.

## World mapping

| Object | Operational meaning |
|---|---|
| Campus / brand rooms | Portfolio and permitted brand scopes |
| Workstation | Durable session, with runtime/node badges |
| Machine rack | Mac node and resource/heartbeat status |
| Work board | Queue and workflow dependency graph |
| Review desk | Pending approvals and operator interventions |
| Artifact shelf | Scoped files, builds, images, and generated media |
| Transfer dock | Explicit checkpoint/handoff progress |

Room location describes business context; node badges describe execution location.
Moving a desk visually does not migrate a process. Avatar proximity does not
grant permission. Unauthorized brands are omitted before scene data reaches
the browser, not merely hidden behind a locked-door mesh.

## Interaction and truth

Click or press an interaction key to open a readable overlay. Offer view,
attach, pause, cancel, resume, or transfer only when the API grants that capability.
Action submissions carry command IDs and expected versions; the object displays
pending until authoritative acknowledgment. Session output uses the scoped stream
and reconnect cursors in FLEET-CONTROL-PLANE-PLAN.md.

Statuses include queued, running, waiting on provider, awaiting human, failed,
completed, stale/offline, and handoff in progress. Use text/icons alongside color.
Completion requires a committed result, not a celebratory animation. Display last
update age and stale badges during disconnect. Scene movement may remain local;
control commands cannot silently queue for execution after authorization expires.

Provide search/jump, filter by brand/runtime/node, and a compact overview for 50
sessions. Keep objects at stable locations so users can develop spatial memory.
Avoid 50 always-rendering terminals; load detail streams on demand. Presence
is optional and separate from execution. Voice/video proximity chat is deferred.

## Nightly prototype milestone

One bounded nightly-build milestone demonstrates a playable room, avatar movement,
10–12 synthetic session objects, status changes, a detail overlay, and a mocked
handoff. Build from fixtures through the same view-model contract intended for
live data. This is a milestone, not an installed recurring automation or a promise
to deliver the full fleet/backend in one night.

Next gates: 50 synthetic sessions and performance test, then read-only live
telemetry, then authorized controls and handoff. First prove the protocol on one
Mac; the scene must use network APIs rather than direct localhost process access.

## Accessibility and performance acceptance

Keep a synchronized list/timeline view with equivalent information and actions.
Keyboard navigation, visible focus, reduced motion, scalable text, and screen
reader details are required. WebGL failure falls back to the list without losing
access. Set a reviewed frame-time budget on the actual operator device; measure
50 visible/session objects separately from 50 terminal streams and compute jobs.
Clean up subscriptions and GPU resources when switching rooms or closing details.

Acceptance: world/list state parity; no unauthorized objects or streams; stale
state visible; server-denied controls stay denied; reconnect restores current
state; moving an avatar causes zero execution effect; submitted commands have
traceable receipts. Browser verification and human visual review precede claims
that the implementation is complete.
