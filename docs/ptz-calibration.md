# PTZ timing calibration

Camera 1 was calibrated on 2026-08-15 while temporarily positioned indoors. These are open-loop timing measurements because the camera's ONVIF position telemetry always reports zero.

## Camera 1 results

All measurements use continuous ONVIF velocity `0.60`. Direction A is the positive ONVIF axis and direction B is the negative axis.

| Axis | Direction | Measured interval | Working estimate | Effective uncertainty |
| --- | --- | ---: | ---: | ---: |
| Vertical | A to B | 2.1875–2.2656 s | 2.2266 s | about 0.08 s |
| Vertical | B to A | 2.3856–2.4264 s | 2.4060 s | about 0.04 s |
| Horizontal | A to B | 6.9531–7.0312 s | 6.9922 s | about 0.20 s |
| Horizontal | B to A | 7.0312–7.1094 s | 7.0703 s | about 0.20 s |

The horizontal uncertainty is governed by the 0.20-second endpoint probe, not the finer 0.078-second binary bracket. The horizontal directions differ by only about 1%. Vertical B-to-A is about 8% slower than A-to-B.

For a normalized position `p`, where A is `0.0` and B is `1.0`:

```text
from A toward B: duration = p × A_to_B_time
from B toward A: duration = (1 - p) × B_to_A_time
```

Examples at velocity `0.60`:

| Axis | A to midpoint | B to midpoint |
| --- | ---: | ---: |
| Vertical | 1.1133 s | 1.2030 s |
| Horizontal | 3.4961 s | 3.5352 s |

The user visually confirmed the vertical A-to-midpoint result. Camera 1 was left at horizontal A and vertical A immediately after calibration, but later capability tests moved it away from that calibrated reference.

## Required ONVIF command shape

This firmware silently ignores some otherwise valid-looking compound PTZ requests. A working continuous pan/tilt request has these properties:

- Use profile token `PROFILE_000`.
- Include the explicit velocity coordinate space `http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace`.
- Include a timeout longer than the intended movement.
- Send only the pan/tilt velocity; do not include an unused zoom vector.
- Finish with an explicit `Stop` request.

## Unsupported advertised movement modes

The PTZ configuration advertises absolute, relative, and continuous coordinate
spaces for both pan/tilt and zoom. That advertisement is not reliable on this
firmware:

- A clean relative pan-only request was accepted but did not move the image.
- Absolute pan requests moved the motor, but the requested coordinates were not
  respected; several different targets produced or retained the same endpoint
  view.
- Clean continuous, absolute, and relative zoom-only requests were all accepted
  without changing the RTSP framing.

Treat absolute movement, relative movement, zoom, and reported position as
unsupported. Only timed continuous pan/tilt followed by an explicit stop is
dependable.

## Calibration process

Use a generous initial duration such as 10–15 seconds to establish a hard stop. The camera's own travel limit stops physical motion even if the continuous command remains active.

For horizontal calibration, do not identify endpoints by comparing against fixed endpoint pictures. Horizontal travel is roughly 340–350 degrees, so the two endpoint views overlap and can resemble one another.

Instead, determine whether a candidate duration reached its stop with a short same-direction probe:

1. Home to direction A with a deliberately oversized command.
2. Capture two stationary images to measure ordinary stream/image noise.
3. Apply a short command farther into the A stop and capture another image. This measures the stopped-probe difference.
4. Move away from A, apply the same short command in free motion, and capture images around it. This measures the moving-probe difference.
5. Choose a threshold safely between the stopped and moving differences.
6. Return to A.
7. Move toward B for a candidate duration and capture an image.
8. Move toward B for the short probe duration and capture again.
9. If the two images differ by less than the threshold, the candidate reached B. Otherwise, it stopped before B.
10. Reset to A and use the result to narrow a binary-search time bracket.
11. Repeat the whole search from B toward A; do not assume equal directional speed.
12. Verify the final upper-bound duration with one more endpoint probe.

Camera 1's horizontal calibration used a 0.20-second probe. Its normalized grayscale image difference was approximately `2` at a hard stop and `35–60` during free movement, providing a clear classification margin.

## Camera-specific streaming quirks

Open a fresh RTSP connection for every calibration still. Long-lived FFmpeg readers were observed returning stale/repeated frames even after the camera physically moved. The firmware also advertises a broken HTTP snapshot URI, so snapshots must be extracted from RTSP.

Ignore or mask the on-screen timestamp when comparing images. Compensate for global brightness changes before calculating a difference because the automatic exposure can shift substantially between views.

## Operational guidance

These timings are sufficient for coarse view selection and occasional sweeps, but they are not encoder-grade coordinates. Motor speed can vary with camera sample, USB supply voltage, temperature, mounting orientation, gravity, wear, and command startup latency.

- Calibrate each camera after final installation and using its permanent power supply.
- Keep separate values for both directions and axes.
- Re-home against a hard stop periodically to eliminate accumulated open-loop error.
- Prefer fewer long moves over many tiny pulses; startup latency dominates short commands.
- Do not try to refine position using equal and opposite tiny pulses; variable command startup latency prevents them from cancelling exactly.
- Do not extrapolate these timings to other velocity settings without recalibration.
- Avoid unnecessary repeated end-stop calibration to reduce motor and gearbox wear.

For the initial coyote detector, fixed camera views are preferable. PTZ timing becomes important only if automated sweeps or repeatable view selection are added later.
