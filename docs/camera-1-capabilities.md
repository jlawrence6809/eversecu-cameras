# Camera 1 capability test

Tested locally on 2026-08-15 and 2026-08-16 against one retail camera running
firmware `2.4`. The vendor app was closed for direct ONVIF/RTSP/P2P tests and
used only where a row explicitly says so. No password, device identifier, or
app token is stored in this project.

## Results

| Function | Result | Notes |
| --- | --- | --- |
| Main video | Pass | RTSP/TCP, H.264, 2304x1296, approximately 12.7 fps during the sample |
| Sub video | Pass | RTSP/TCP, H.264, 640x360, approximately 12.5 fps during the sample |
| Microphone/audio input | Pass with workaround | G.711 A-law, mono, 8 kHz. Each 160-byte audio payload has a private four-byte header; treating it as audio produces a 50 Hz buzz. Stripping the header yields intelligible audio, confirmed by the user. |
| Still image | Workaround | ONVIF returns `http://CAMERA_IP:80/snapshot.cgi`, but port 80 refuses connections. Capture a frame from RTSP instead. |
| Brightness | Pass | Set from 50 to 55, verified by readback, restored to 50 |
| Color saturation | Pass | Set from 50 to 55, verified by readback, restored to 50 |
| Contrast | Pass | Set from 50 to 55, verified by readback, restored to 50 |
| Sharpness | Pass | Set from 50 to 55, verified by readback, restored to 50 |
| Backlight compensation | Pass | Enabled, verified, restored to off |
| Wide dynamic range | Pass | Enabled, verified, restored to off |
| Exposure limit | Pass | Changed from 40000 to 50000, verified, restored to 40000; exposure mode is auto-only |
| IR-cut filter | Pass | Forced on and off, then restored to auto. This controls the optical filter, not IR LED power. |
| White balance | Limited | Camera exposes auto mode only |
| Continuous pan over ONVIF | Pass | The working command requires an explicit velocity coordinate space and timeout, with no unused zoom vector. At velocity `0.60`, stop-probe binary search measured A-to-B at 6.9531–7.0312 seconds (midpoint 6.9922) and B-to-A at 7.0312–7.1094 seconds (midpoint 7.0703). |
| Continuous tilt over ONVIF | Pass | At velocity `0.60`, endpoint-image binary search measured A-to-B travel between 2.1875 and 2.2656 seconds (midpoint 2.2266) and B-to-A travel between 2.3856 and 2.4264 seconds (midpoint 2.4060). The reverse direction is about 8% slower. |
| Absolute/relative pan and tilt | Fail / unsafe | A clean relative pan-only request was accepted but produced no image change. Absolute requests can move the motor, but different target coordinates were ignored and led to or remained at the same endpoint view. Do not use either mode; use continuous movement plus explicit stop instead. |
| PTZ position status | Broken | Always reports pan, tilt, and zoom as zero, including after confirmed physical movement |
| Zoom over ONVIF | Fail / false capability | The camera advertises continuous, absolute, and relative zoom spaces and accepts clean zoom-only requests in all three modes. Tests at continuous velocity `+0.60`, absolute position `1.0`, and relative translation `+1.0` produced identical RTSP framing. There is no usable zoom control. |
| PTZ home/presets | Fail | Home and preset operations return `Action Not Implemented` |
| Motion event subscription | Fail | A motion topic is advertised, but subscription creation returns `Action Not Implemented` |
| Speaker/talk-back | Pass through app and direct local P2P | O-KAM two-way intercom was audibly verified in both directions. The outbound stream is mono 16 kHz G.711 A-law: 640-byte/40 ms frames (media type `0x08`) on P2P channel 3. A capture contained 458 consecutive unique frames and explicit camera ACKs. `scripts/okam_p2p_talk.py` reproduced the app's login/media initialization and direct playback of a spoken phrase was physically confirmed by the user. ONVIF audio output and RTSP backchannel remain unsupported. |
| White spotlight | Pass through app and direct local P2P | The physical white LEDs were visibly confirmed through O-KAM, then ON, status, and OFF were independently verified with `scripts/okam_p2p_control.py`. The camera explicitly returned `result="ok"` and the requested `lightStatus`. Auto exposure takes roughly 1–2 seconds to recover after either transition. No ONVIF control is exposed. |
| IR illuminator LEDs | Pass through app and direct local P2P | The local `param=14` control was visually mapped in a dark room: value 0 forced the IR illumination off, value 1 forced the IR LEDs and black-and-white mode on, and value 2 selected automatic mode. The mechanical IR-cut filter click and lit emitters were physically confirmed. `scripts/okam_p2p_control.py` exposes these as `ir-off`, `ir-on`, and `ir-auto`. No ONVIF LED-power control is exposed. |
| Siren | Pass through app and direct local P2P | `cmd=2109` with `siren=1` and `siren=0` was physically verified. The camera returned `sirenStatus=1` while sounding and `sirenStatus=0` after cleanup; a final query confirmed it remained off. `scripts/okam_p2p_control.py` exposes `siren-on` and `siren-off`. No ONVIF control is exposed. |
| Humanoid auto-tracking | Pass through app and direct local P2P | Local command `cmd=2127` enables, disables, and queries onboard person tracking. Direct enable/readback returned `enable=1`; the live `track_status` changed from 0 to 1 when a person entered view, and an RTSP snapshot confirmed that the camera physically rotated to follow. `scripts/okam_p2p_control.py` exposes `track-on`, `track-off`, and `track-status`. No ONVIF analytics configuration is exposed. |
| Humanoid detection/alerts | Partially identified | The vendor SDK maps humanoid detection to `cmd=2106`, separately from tracking. Its configuration and alert delivery have not been bench-tested because tracking itself does not require them. |
| SD-card recordings | App-only | No ONVIF recording service is exposed |
| On-screen display | Unavailable | OSD support is reported as false |

The imaging test used non-persistent writes and restored every touched value after each check, followed by a final safety restore. An initial PTZ test was ignored because of the firmware's strict command parsing; a later correctly shaped continuous-pan command was visually confirmed by the user. The coordinate-mode tests show that the advertised PTZ configuration overstates the firmware's real capabilities. No network settings, firmware functions, reboot, factory reset, or permanent home/preset changes were attempted.

## Practical interface for the coyote project

Use RTSP for video and microphone audio, extract local still frames when needed, and perform motion/animal detection on the Mac. The reliable standards-based controls currently include the imaging settings and continuous pan/tilt using the camera's strict command format. The white spotlight, IR night mode, talk-back speaker, siren, and onboard humanoid tracking can also be controlled over the now-documented local O-KAM P2P transport. Detection alerts and storage still require the vendor app or additional protocol work.

Example still-frame capture from the substream:

```sh
ffmpeg -rtsp_transport tcp \
  -i 'rtsp://admin:PASSWORD@CAMERA_IP:10554/tcp/av0_1' \
  -frames:v 1 frame.jpg
```
