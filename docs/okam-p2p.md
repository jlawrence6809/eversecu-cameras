# O-KAM local P2P protocol

Bench tested against one firmware `2.4` camera on 2026-08-15. The direct white-light and IR-mode
controller works entirely on the LAN with O-KAM closed.

## Confirmed result

The app's ON/OFF/ON/OFF sequence produced four 148-byte UDP control frames.
After decryption, their request bodies were exactly:

```text
GET /trans_cmd_string.cgi?cmd=2109&command=0&light=1&...
GET /trans_cmd_string.cgi?cmd=2109&command=0&light=0&...
GET /trans_cmd_string.cgi?cmd=2109&command=0&light=1&...
GET /trans_cmd_string.cgi?cmd=2109&command=0&light=0&...
```

The status query is:

```text
GET /trans_cmd_string.cgi?cmd=2109&command=2&...
```

The direct client subsequently received successful ON, OFF, and status
responses, including the requested `lightStatus`. Anonymous placeholder
credentials were rejected, so the client reads the app's user ID and short
login token from `OKAM_USER_ID` and `OKAM_LOGIN_PASS`. These are separate from
the camera's ONVIF/RTSP administrator password and must not be committed.

## Confirmed infrared night-mode control

The app binary exposed the generic camera parameter request below, and a
dark-room bench test established all three value mappings:

```text
GET /camera_control.cgi?param=14&value=0&...  # force daytime / IR off
GET /camera_control.cgi?param=14&value=1&...  # force IR night mode on
GET /camera_control.cgi?param=14&value=2&...  # automatic day/night selection
```

For each write, the camera returned `result="ok"`; `get_camera_params.cgi`
then reported the selected value as `ircut`. With the room dark, value 0 made
the RTSP frame substantially darker, value 1 produced strong near-infrared
illumination and a black-and-white image, and value 2 automatically produced
the same IR-lit result as value 1. The mechanical filter click and IR emitters
were also physically confirmed. The camera was restored to value 2 after that
test.

The app also contains a lower-level command:

```text
GET /trans_cmd_string.cgi?cmd=2120&command=0&InfraredLaser=VALUE&...
```

`InfraredLaser=1` physically engaged the filter and IR emitters, but the
generic parameter control is preferable because it expresses persistent
forced-off, forced-on, and automatic modes and has a readable `ircut` value.

## Confirmed siren control

The siren shares command 2109 with the white spotlight:

```text
GET /trans_cmd_string.cgi?cmd=2109&command=0&siren=1&...  # on
GET /trans_cmd_string.cgi?cmd=2109&command=0&siren=0&...  # off
GET /trans_cmd_string.cgi?cmd=2109&command=2&...          # status
```

The camera explicitly returned `sirenStatus=1` and sounded during the ON test,
then returned `sirenStatus=0` after OFF. A final status query independently
confirmed that both the siren and white spotlight were off. The alarm was
physically confirmed on 2026-08-16.

## Confirmed humanoid auto-tracking

The vendor SDK maps humanoid tracking to command 2127:

```text
GET /trans_cmd_string.cgi?cmd=2127&command=0&enable=1&...  # enable
GET /trans_cmd_string.cgi?cmd=2127&command=0&enable=0&...  # disable
GET /trans_cmd_string.cgi?cmd=2127&command=1&...           # status
```

The status response contains persistent `enable` and live `track_status`
fields. The test camera initially returned both as 0. After a direct local enable it
confirmed `enable=1`; when a person entered view, `track_status` changed to 1
and an RTSP snapshot showed that the camera had physically rotated from its
previous bench view to follow the subject. It returned to 0 when tracking was
idle and changed back to 1 on reacquisition.

While the motor was actively tracking, some independent P2P status sessions
timed out. A controller should tolerate an occasional missed poll and avoid
high-frequency status requests. `scripts/okam_p2p_control.py` provides
`track-on`, `track-off`, and `track-status` with readback verification.

The SDK exposes ordinary humanoid detection separately through command 2106.
That setting and the app/cloud alert path are not required for motor tracking
and have not yet been changed or bench-tested.

## UDP session and framing

The app first discovers the camera on UDP port 32108. The camera moves the
session to a dynamic UDP port; the tested sessions remained direct between the
Mac and camera rather than passing through a cloud relay.

The observed control exchange is:

1. Send the encrypted `f1 30 00 00` discovery packet to UDP 32108.
2. Echo the camera's `f1 41` challenge to the dynamic source port.
3. Accept the `f1 42` or `f1 43` session-ready packet.
4. Send `f1 e0 00 00` and open logical channel `d1 07`.
5. Put the ASCII CGI request in an `f1 d0` reliable-data frame on logical
   channel `d1 00`.
6. Acknowledge the two-byte control-channel response sequence with an `f1 d1`
   frame. Without this ACK, the camera retransmits its result.

The request length is little-endian inside the logical-channel frame, while
the outer `f1 d0` payload length is big-endian. The implementation is in
[`scripts/okam_p2p_control.py`](../scripts/okam_p2p_control.py).

## Confirmed talk-back audio

A process-filtered O-KAM Pro capture produced 564 app-to-camera packets on
logical channel `d1 03`. After removing byte-identical retransmissions, the
stream contained sequence numbers 0 through 457 with no gaps: 18.32 seconds
of audio in 458 frames.

The app brackets transmission with these control requests:

```text
GET /get_status.cgi?name=admin&...    # sent twice to authenticate the session
GET /livestream.cgi?streamid=10&substream=2&...  # initialize media
GET /audiostream.cgi?streamid=7&...   # immediately before talk frames
GET /audiostream.cgi?streamid=16&...  # immediately after talk frames
GET /livestream.cgi?streamid=16&substream=0&...  # stop media
```

Every talk frame is one complete 680-byte encrypted UDP packet:

```text
f1 d0 02 a4 d1 03 SS SS              # reliable-data/channel/sequence
55 aa 15 a8 08 01 00 00              # media magic/type/stream
00 00 00 00 00 00 00 00
80 02 00 00 00 00 00 00              # 0x280 = 640 payload bytes
00 00 00 07 00 00 00 00
[640 bytes G.711 A-law audio]
```

The payload is mono 16 kHz G.711 A-law. A 640-byte frame therefore represents
40 ms, and the app sends 25 frames per second. In the capture, the median
first-send interval was 37.76 ms and the mean was exactly 40.00 ms. The camera
acknowledged channel `d1 03`; its app-side transport retransmitted 106 packets,
all byte-identical to their original sequence.

[`scripts/okam_p2p_talk.py`](../scripts/okam_p2p_talk.py) reproduces this exact
sequence and framing. It accepts an arbitrary audio file through FFmpeg or can
generate a short low-volume bench-test tone. Direct playback initially stayed
silent until the client reproduced the app's media setup: two
`get_status.cgi?name=admin` login exchanges followed by a live-substream start.
With that initialization in place, the camera audibly played a synthesized
spoken phrase; the user physically confirmed it on 2026-08-16. The client then
stopped both audio and video streams.

## Transport cipher and security implication

The payload cipher uses a fixed substitution table and the static key
`vstarcam2019`. The table and algorithm match the independently documented
[VStarcam P2P decryptor](https://github.com/BrownFineSecurity/vstarcam-p2p-decrypt),
whose MIT notice is retained in [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).
This is obfuscation rather than meaningful transport security: anyone able to
capture the LAN session can recover the CGI requests and app P2P identity.
That reinforces the plan to place the cameras on an isolated IoT network and
deny unnecessary outbound internet access.

Packet captures are kept under the ignored `captures/` directory because they
contain encrypted-but-recoverable identifiers and credentials.

## Remaining unverified commands recovered from the app

The O-KAM binary also contains these promising next targets:

```text
trans_cmd_string.cgi?cmd=2120&command=1&
```

This likely queries the lower-level IR laser/filter status, but its response
fields have not yet been established. The preferred `param=14` IR mode already
has a verified readback.
