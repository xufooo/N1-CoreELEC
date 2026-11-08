#!/usr/bin/env python3
"""Render the verification summary as GitHub step-summary markdown."""
import json
import sys


def main():
    summary = json.load(open(sys.argv[1], encoding='utf-8'))
    out = []
    out.append('### DV metadata host verification')
    out.append('')
    out.append('| group | cases | pass | fail | expected-fail |')
    out.append('|---|---|---|---|---|')
    for group in summary.get('groups', []):
        out.append('| %s | %d | %d | %d | %d |' % (
            group['name'], group['cases'], group['pass'], group['fail'],
            group.get('expected_fail', 0)))
    out.append('')
    out.append('verdict: **%s** - fixtures %d, frames %d, DM bytes compared %d' % (
        summary.get('verdict'), summary.get('fixtures', 0),
        summary.get('frames', 0), summary.get('dm_bytes_compared', 0)))
    out.append('')
    defects = [r for r in summary.get('rows', []) if r['status'] == 'KNOWN_DEFECT']
    if defects:
        out.append('#### Recorded defects (not passes)')
        out.append('')
        for row in defects:
            out.append('- `%s` %s' % (row['name'], row['detail']))
        out.append('')
    failures = summary.get('failures', [])
    if failures:
        out.append('#### Failures')
        out.append('')
        for row in failures[:10]:
            out.append('- `%s/%s` %s' % (row['group'], row['name'], row['detail']))
        out.append('')
    for note in summary.get('notes', []):
        out.append('> ' + note)
    print('\n'.join(out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
