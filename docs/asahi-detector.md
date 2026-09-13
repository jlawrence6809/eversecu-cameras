# Fedora Asahi detector deployment

The detector uses native FFmpeg (Fedora ffmpeg-free provides libopenh264) and
CPU-only PyTorch. Linux dependencies select the explicit official PyTorch CPU
index in pyproject.toml; uv.lock records the resolution. Do not copy macOS venvs.

Python 3.13 is installed with uv, then copied into /opt/eversecu/python for the
system service. Create /opt/eversecu/venv using that interpreter and run from
detector/:

```
sudo env UV_PROJECT_ENVIRONMENT=/opt/eversecu/venv uv sync --frozen --python /opt/eversecu/python/bin/python3.13
sudo restorecon -RF /opt/eversecu
```

Install detector/eversecu-detector.service in /etc/systemd/system and enable it
only through private-services.target. It runs as jeremy, writes only into the
vault, and is stopped before vault unmount. Source remains in ~/code/eversecu-cameras.
The home-directory Python failed system-service execution; /opt deployment works
without disabling SELinux.

Credential-bearing detector.env, events and health state reside under
/var/lib/private-services/camera. Never commit or print them. RTSP input is
passed through an inherited pipe using an FFmpeg concat list, rather than
putting the credential-bearing URL in argv. Quoted/newline input is rejected;
FFmpeg errors retain existing URL redaction. No camera movement, lights or siren
commands are part of this deployment.

Verified on Asahi: 10 unit tests, CPU model load, one-frame camera decode/run,
systemd startup and streaming heartbeat. This is not a long-term soak or a
validated coyote classifier. Existing model identifies canine candidates.

## Watchdog (verified 2026-09-13)

Jeremy authorized a dedicated camera-watchdog account on the new XMPP domain,
initially with alerts addressed only to his human account. At Jeremy's request,
alerts now post instead to camera-alerts on the existing rooms component.
The room is persistent, unlisted and members-only, with Jeremy as owner and
camera-watchdog as a member. At Jeremy's request, the existing Asahi migration
conversation was subsequently granted membership; its room archive read passed.
This grants on-demand access, not automatic room monitoring. Jeremy can grant
other agents membership later. Archived room reads and synthetic failure/deduplication/
recovery posts passed; 12 unit tests pass. Existing DMs remain in their archive.
Join camera-alerts@rooms.jlawrence6809.tail1b2a0d.ts.net in Gajim.
The service explicitly selects --room; --recipient retains legacy DM support.
The account profile and password live in camera/xmpp inside the vault. The
agent-xmpp CLI is installed from the local migration checkout into a separate
/opt/eversecu/xmpp virtual environment; never reuse old macOS credentials.

Install watch_connection.py root-owned at /opt/eversecu/watch_connection.py and
the eversecu-watchdog service/timer into /etc/systemd/system. Enable the timer
under private-services.target. Its first check waits five minutes after target
startup; subsequent checks run one minute after the preceding check completes.
A frame older than five minutes triggers one systemd detector restart and one
room post. Recovery sends another room post. Restart deduplication is persisted before the
restart request, so failed XMPP delivery does not cause repeated restarts.

The watchdog runs as root to request the fixed detector unit restart; code and
Python runtimes under /opt are root-owned. Its sandbox is read-only except for
camera vault state, hides home directories, disables privilege acquisition and
core dumps. The detector itself still runs as jeremy. Lock helpers explicitly
stop the watchdog timer and service before unmount; both units are also PartOf
the vault target. Unlock requires the LONG service-vault passphrase, not the
shorter system password or Restic password.

Verified: 11 unit tests including systemd restart deduplication; real XMPP
synthetic failure/recovery delivery and suppression of duplicate failure;
sandboxed service recovery delivery; restart helper against a harmless temporary
systemd unit; live detector remains streaming. Synthetic tests do not interrupt
the camera or request its restart. Jeremy confirmed visual receipt of the original DMs in Gajim. Full vault
lock/reboot/unlock with camera and backup units passed on 2026-09-13: remote
access returned while the vault stayed locked, and camera streaming plus all
timers resumed after attended unlock. XMPP/server loss prevents
alerts until service returns; this is not independent off-host monitoring.
