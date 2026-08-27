# EVERSECU / O-KAM camera tools

Unofficial local-control tools and reverse-engineering notes for the EVERSECU
2K 3MP outdoor Wi-Fi PTZ camera sold in a four-pack and configured with the
O-KAM Pro app. Testing was performed on firmware `2.4`.

This project is not affiliated with EVERSECU, O-KAM, or the camera
manufacturer. Camera firmware and hardware can change without the retail
listing changing, so verify commands carefully on your own unit.

## What works

| Function | Local interface | Status |
| --- | --- | --- |
| Main video | RTSP/TCP, H.264, 2304x1296 | Verified |
| Sub video | RTSP/TCP, H.264, 640x360 | Verified |
| Microphone | RTSP, mono 8 kHz G.711 A-law | Verified with framing workaround |
| Pan and tilt | ONVIF timed continuous movement | Verified |
| White spotlight | O-KAM LAN protocol | Verified |
| IR day/night modes | O-KAM LAN protocol | Verified |
| Siren | O-KAM LAN protocol | Verified |
| Speaker/talk-back | O-KAM LAN protocol, mono 16 kHz G.711 A-law | Verified |
| Humanoid auto-tracking | O-KAM LAN protocol | Verified |

Absolute/relative PTZ positioning, zoom, ONVIF events, presets, and the
advertised HTTP snapshot URI are not usable on the tested firmware. See the
[full capability matrix](docs/camera-1-capabilities.md) and
[PTZ calibration notes](docs/ptz-calibration.md) for details. The
[hardware notes](docs/hardware.md) record board markings and initial UART/SPI
investigation guidance from a disassembled unit.

## Requirements

- Python 3.10 or newer
- [FFmpeg](https://ffmpeg.org/) for RTSP inspection, microphone recording, and
  talk-back conversion
- [`onvif-zeep`](https://github.com/FalkTannhaeuser/python-onvif-zeep) for the
  read-only ONVIF probe
- A camera on the same trusted LAN as the computer running these tools

On macOS with Homebrew, the external dependencies can be installed with:

```sh
brew install ffmpeg uv
```

## Standard local endpoints

Replace `CAMERA_IP` with the address assigned by your router. Supply the
camera's `admin` password through your client; never put a real password in a
committed URL.

- ONVIF device service: `http://CAMERA_IP:10080/onvif/device_service`
- Main RTSP stream: `rtsp://CAMERA_IP:10554/tcp/av0_0`
- Sub RTSP stream: `rtsp://CAMERA_IP:10554/tcp/av0_1`

For example, open a stream with VLC using:

```text
rtsp://admin:PASSWORD@CAMERA_IP:10554/tcp/av0_0
```

## Read-only camera probe

The probe reports ONVIF capabilities and inspects both RTSP streams. It does
not change settings and does not print the password. Its output can include a
camera serial number and network identifiers, so review it before sharing.

```sh
export CAMERA_IP='192.0.2.10'
export CAMERA_PASSWORD='your-camera-password'
uv run --with onvif-zeep python scripts/camera_probe.py "$CAMERA_IP"
```

## Record microphone audio

The camera inserts an undocumented four-byte header before every 160-byte
audio payload. Decoding the original stream directly causes a 50 Hz buzz. The
interactive recorder removes that framing and creates a normal WAV file:

```sh
export CAMERA_IP='192.0.2.10'
python3 scripts/record_camera_audio.py --host "$CAMERA_IP"
```

Recordings under `samples/` are ignored by Git. For an already captured raw
A-law stream, `scripts/strip_okam_audio_header.py` can remove the framing
without recording again.

## Control lights, siren, and tracking

The non-ONVIF controls use O-KAM's local UDP protocol and do not contact an
O-KAM cloud service. They require the P2P identity sent by the app, which is
distinct from the ONVIF/RTSP password. Discovery of those values is not yet
automated; see the [protocol notes](docs/okam-p2p.md). Keep them in environment
variables and never publish a packet capture containing them.

```sh
export CAMERA_IP='192.0.2.10'
export OKAM_USER_ID='captured-app-user-id'
export OKAM_LOGIN_PASS='captured-app-login-token'

python3 scripts/okam_p2p_control.py "$CAMERA_IP" status
python3 scripts/okam_p2p_control.py "$CAMERA_IP" on
python3 scripts/okam_p2p_control.py "$CAMERA_IP" off

python3 scripts/okam_p2p_control.py "$CAMERA_IP" ir-off
python3 scripts/okam_p2p_control.py "$CAMERA_IP" ir-on
python3 scripts/okam_p2p_control.py "$CAMERA_IP" ir-auto

python3 scripts/okam_p2p_control.py "$CAMERA_IP" siren-on
python3 scripts/okam_p2p_control.py "$CAMERA_IP" siren-off

python3 scripts/okam_p2p_control.py "$CAMERA_IP" track-status
python3 scripts/okam_p2p_control.py "$CAMERA_IP" track-on
python3 scripts/okam_p2p_control.py "$CAMERA_IP" track-off
```

The controller waits for the camera's explicit success response and verifies
the returned state. `ir-off` forces daytime mode, `ir-on` forces the IR LEDs
and black-and-white mode, and `ir-auto` selects a mode from ambient light.

## Play audio through the speaker

FFmpeg converts a file or generated test tone to the camera's talk-back
format. The same `OKAM_USER_ID` and `OKAM_LOGIN_PASS` environment variables
are required.

```sh
python3 scripts/okam_p2p_talk.py "$CAMERA_IP" --tone 0.8
python3 scripts/okam_p2p_talk.py "$CAMERA_IP" --file announcement.wav
```

The script limits audio to 30 seconds by default. Use `--dry-run` to test
conversion without contacting the camera.

## Security notes

The O-KAM LAN protocol uses a static substitution cipher, not meaningful
transport security. Anyone able to capture the traffic can recover its CGI
requests and P2P identity. Put the camera on an isolated IoT network or VLAN,
block unnecessary internet access, use a unique camera password, and do not
expose its RTSP, ONVIF, or P2P ports directly to the internet.

Packet captures and recordings are deliberately excluded from this
repository because they can contain credentials, identifiers, private audio,
or video.

## Coyote/canine detector

The optional [local coyote detector](docs/coyote-detector.md) samples the RTSP
substream and saves evidence frames for canine candidates. Its deliberately
conservative first stage treats the general-purpose model's `dog` class as a
possible dog, coyote, or similar animal, providing useful alerts and a local
dataset without overstating species-level accuracy.

## License

The original code and documentation are released under the [MIT License](LICENSE).
The incorporated VStarcam cipher table retains its upstream attribution in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
