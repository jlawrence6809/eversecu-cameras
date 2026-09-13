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

Remaining: Linux watchdog restart integration, new-domain XMPP alert account
and recipient selection, failure/recovery notification tests, and full vault
lock/unlock with the detector included. No watchdog alert delivery is claimed.
