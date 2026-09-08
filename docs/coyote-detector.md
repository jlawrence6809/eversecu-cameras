# Coyote detector

The first detector stage watches the low-resolution RTSP stream and saves an
annotated frame whenever TorchVision's COCO model finds a `dog`. This is
intentionally called a **canine candidate**, not a confirmed coyote: generic
models commonly map coyotes to the dog class and cannot reliably distinguish a
pet dog from a coyote.

This conservative first stage is useful immediately and collects the real
day/night examples needed to train or evaluate a coyote-versus-dog classifier.
No camera image leaves the local network.

## Install

From the repository root:

```sh
cd detector
cp .env.example .env
chmod 600 .env
```

Edit `.env` with the camera's current address. The file is ignored by Git. On
macOS, store the camera password in the login Keychain; the final `-w` option
prompts without putting the password in shell history:

```sh
security add-generic-password -U \
  -a admin -s eversecu-coyote-camera -w
```

Install and run with [uv](https://docs.astral.sh/uv/):

```sh
uv sync
uv run python coyote_watch.py --once
uv run python coyote_watch.py
```

The first run downloads the approximately 14 MB SSDLite weights. Candidate
frames and JSON metadata are written under `detector/events/`, grouped by day,
and are ignored by Git. The default retention period is 14 days.

## Run continuously on macOS

After the one-frame test succeeds, install the per-user launch agent:

```sh
uv run python install_macos_service.py
```

The agent starts immediately, restarts after failures, and loads again whenever
the user logs in. Logs are written under
`~/Library/Logs/eversecu-coyote-detector/`. Inspect its current state with:

```sh
launchctl print gui/$(id -u)/com.jlawrence6809.eversecu-coyote-detector
tail -f ~/Library/Logs/eversecu-coyote-detector/stderr.log
```

## Connection recovery and health alerts

The detector gives the camera a 30-second quiet period after a broken RTSP
session, then doubles the delay up to five minutes if reconnection continues to
fail. This avoids keeping the tested firmware in its non-recovering rapid-retry
state. `state/health.json` is updated atomically while frames are decoded and
contains no credentials.

`watch_connection.py` can run independently once per minute and send a single
XMPP DM when frames have been stale for five minutes. It suppresses repeats and
sends one recovery DM when frames resume. On macOS, after installing and
initializing the `agent-xmpp` CLI, install the launch agent with the exact
destination conversation JID:

```sh
uv run python install_macos_watchdog.py \
  --recipient c-example@xmpp.example
```

The watchdog catches a dead detector process because the health heartbeat also
goes stale. It cannot report a total Mac, LAN, Tailscale, Prosody, or power
failure because its XMPP client and the initial Prosody server share the same
Mac. Delivery can trigger work only while the destination runtime and its
supervised XMPP bridge attachment remain available; automatic wake or resume of
a closed agent runtime is not currently provided by `agent-xmpp`.

## Initial operating settings

- Infer on one frame per second from the 640x360 substream.
- Save detections at confidence 0.35 or greater.
- Limit evidence frames to one every 30 seconds while a canine remains visible.
- Delete evidence after 14 days.
- Wait 30 seconds before the first reconnect and back off to at most 5 minutes.
- Treat a frame heartbeat older than 5 minutes as unhealthy.

These values are starting points. Review false negatives before increasing the
confidence threshold. A coyote that is small in the frame is more likely to
have low confidence.

## Planned second stage

After the camera has collected representative events:

1. Label candidates as coyote, dog, fox, or other.
2. Evaluate a local second-stage classifier on the cropped animal images.
3. Add buffered main-stream video clips around each accepted event.
4. Send phone notifications only after event grouping and classification are
   stable enough to avoid alert storms.
