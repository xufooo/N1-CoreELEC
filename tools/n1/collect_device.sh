#!/bin/sh
# Read-only N1 playback diagnostics. Run before and after the audio problem.
# Store the output locally; this script does not upload it or change services.
printf '\n== CoreELEC ==\n'
cat /etc/os-release
uname -a
printf '\n== Board ==\n'
for field in model compatible coreelec-dt-id; do
  if [ -r "/proc/device-tree/$field" ]; then
    printf '%s: ' "$field"
    tr '\000' ' ' < "/proc/device-tree/$field"
    printf '\n'
  fi
done
printf '\n== Network addresses ==\n'
for path in /sys/class/net/*/address; do
  [ -r "$path" ] || continue
  printf '%s: ' "$path"
  cat "$path"
done
printf '\n== Factory MAC kernel parameters ==\n'
for arg in $(cat /proc/cmdline); do
  case "$arg" in mac=*|mac_wifi=*|mac_bt=*) printf '%s\n' "$arg";; esac
done
printf '\n== Audio cards ==\n'
cat /proc/asound/cards 2>/dev/null
if command -v aplay >/dev/null 2>&1; then aplay -l; fi
if command -v amixer >/dev/null 2>&1; then
  for card in /proc/asound/card[0-9]*; do
    [ -d "$card" ] || continue
    number=${card##*/card}
    printf '\n== Audio mixer card %s ==\n' "$number"
    amixer -c "$number" contents
  done
fi
printf '\n== HDMI state ==\n'
for path in /sys/class/amhdmitx/amhdmitx0/attr /sys/class/amhdmitx/amhdmitx0/disp_cap \
            /sys/class/amhdmitx/amhdmitx0/dv_cap /sys/class/amhdmitx/amhdmitx0/aud_cap; do
  if [ -r "$path" ]; then printf '%s:\n' "$path"; cat "$path"; fi
done
printf '\n== NTFS helper ==\n'
ls -l /usr/sbin/mount.ntfs /usr/bin/ntfs-3g 2>/dev/null
printf '\n== Recent audio transitions ==\n'
if [ -r /storage/.kodi/temp/kodi.log ]; then
  grep -E 'CAESinkALSA|CActiveAESink::OpenSink|aml_set_audio_passthrough' \
    /storage/.kodi/temp/kodi.log | tail -100
fi
