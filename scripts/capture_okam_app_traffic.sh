#!/bin/zsh

# Capture O-KAM Pro traffic for a bounded amount of time. This helper is
# intended to be invoked through macOS `do shell script ... with administrator
# privileges`; its watchdog uses SIGKILL because tcpdump may inherit ignored
# interactive signals when launched by a non-interactive privileged shell.

set -euo pipefail

if (( $# != 2 )); then
  print -u2 "usage: $0 OUTPUT.pcapng DURATION_SECONDS"
  exit 2
fi

capture_path=$1
duration_seconds=$2

if [[ $capture_path != /* || $capture_path != *.pcapng ]]; then
  print -u2 "output must be an absolute .pcapng path"
  exit 2
fi

if [[ $duration_seconds != <1-120> ]]; then
  print -u2 "duration must be an integer from 1 through 120 seconds"
  exit 2
fi

/usr/sbin/tcpdump \
  -i pktap,all \
  -Q 'proc=Runner' \
  -s 0 \
  -U \
  -w "$capture_path" &
capture_pid=$!

(
  /bin/sleep "$duration_seconds"
  /bin/kill -KILL "$capture_pid" 2>/dev/null || true
) &
watchdog_pid=$!

capture_status=0
wait "$capture_pid" || capture_status=$?

/bin/kill -KILL "$watchdog_pid" 2>/dev/null || true
wait "$watchdog_pid" 2>/dev/null || true

# SIGKILL is the watchdog's expected bounded-exit status.
if (( capture_status != 0 && capture_status != 137 )); then
  exit "$capture_status"
fi

exit 0
