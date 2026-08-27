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

## Initial operating settings

- Infer on one frame per second from the 640x360 substream.
- Save detections at confidence 0.35 or greater.
- Limit evidence frames to one every 30 seconds while a canine remains visible.
- Delete evidence after 14 days.

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
