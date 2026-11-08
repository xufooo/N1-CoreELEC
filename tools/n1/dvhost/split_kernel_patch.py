#!/usr/bin/env python3
"""Extract `dv_injection.c` out of the repository kernel patch.

The patch adds the file wholesale (`new file mode`), so the hunk body is the
file content with a leading '+' on every line.
"""
import argparse
import sys

TARGET = 'drivers/amlogic/media/video_sink/dv_injection.c'


def extract(patch_path, target=TARGET):
    lines = open(patch_path, encoding='utf-8', errors='replace').read().splitlines(True)
    out = []
    state = None
    in_hunk = False
    for ln in lines:
        if ln.startswith('+++ b/'):
            path = ln[6:].strip()
            state = 'collect' if path.endswith(target) else 'skip'
            in_hunk = False
            continue
        if ln.startswith('--- a/') or ln.startswith('diff --git') or ln.startswith('index '):
            if not ln.startswith('index '):
                if state == 'collect' and in_hunk:
                    state = 'skip'
            continue
        if state != 'collect':
            continue
        if ln.startswith('@@'):
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if ln.startswith('+'):
            out.append(ln[1:])
        elif ln.startswith(' '):
            out.append(ln[1:])
        elif ln.startswith('\\'):
            continue
        else:
            in_hunk = False
    if not out:
        raise SystemExit('no %s found in %s' % (target, patch_path))
    return ''.join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--patch', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    text = extract(args.patch)
    with open(args.out, 'w', encoding='utf-8') as f:
        f.write(text)
    print('extracted %s: %d bytes, %d lines' % (args.out, len(text), text.count('\n')))
    for marker in ('dv_injection_validate_metadata', 'dv_injection_pack_bytes',
                   'dv_injection_expand_pixels', 'dv_injection_block_length'):
        if marker not in text:
            raise SystemExit('extracted file lacks %s' % marker)
    return 0


if __name__ == '__main__':
    sys.exit(main())
