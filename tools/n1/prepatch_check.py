#!/usr/bin/env python3
"""Static sanity gate for the kernel files touched by the DV injection patch.

The host tests in tools/n1 extract the module C from the repository patch, so
they never compile hdmi_tx_hw.c / hdmi_tx_main.c.  Two builds were lost to
edits that clobbered a function parameter list (every line of the body then
parsed at file scope).  This gate catches that class before a push:

  * balanced braces and parentheses over the whole translation unit
  * no ';' inside the parameter list of a top level function definition
  * no stray '"' breaking a string literal
  * every 'deleted' line in the patch is listed so it can be eyeballed

Usage: prepatch_check.py <patched-tree-root> [patch-file] [--pristine <dir>]
Exit code 0 only when every check passes.
"""

import os
import re
import sys

C_SUFFIX = (".c", ".h")


def strip_comments_and_strings(src):
    """Blank out comments and literals, returning (text, problems)."""
    out = []
    problems = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            if j < 0:
                problems.append("unterminated block comment at line %d"
                                % (src[:i].count("\n") + 1))
                out.append(" " * (n - i))
                i = n
            else:
                j += 2
                out.append(" " * (j - i))
                i = j
        elif c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif c in "\"'":
            quote = c
            j = i + 1
            terminated = False
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "\n":
                    break
                if src[j] == quote:
                    terminated = True
                    j += 1
                    break
                j += 1
            if not terminated:
                problems.append("unterminated %s literal at line %d"
                                % ("string" if quote == '"' else "char",
                                   src[:i].count("\n") + 1))
            out.append(" " * (j - i))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out), problems


def counts(text):
    """(braces, parens, brackets) imbalance for text with literals blanked."""
    clean, _ = strip_comments_and_strings(text)
    return (clean.count("{") - clean.count("}"),
            clean.count("(") - clean.count(")"),
            clean.count("[") - clean.count("]"))


def check_file(path, rel, pristine_path=None):
    problems = []
    raw = open(path, "r", errors="replace").read()
    base = counts(open(pristine_path, "r", errors="replace").read()) if pristine_path else (0, 0, 0)

    clean, lit_problems = strip_comments_and_strings(raw)
    for msg in lit_problems:
        problems.append("%s: %s" % (rel, msg))

    # Compare with the pristine file: several vendor files already contain an
    # unbalanced brace inside disabled code, which is not our regression.
    here = counts(raw)
    for idx, name in ((0, "brace"), (1, "paren"), (2, "bracket")):
        if here[idx] != base[idx]:
            problems.append(
                "%s: %s balance changed by the patch (%+d, pristine %+d)"
                % (rel, name, here[idx], base[idx])
            )

    # A parameter list that opens at the end of a top level line must not
    # contain a ';' before it closes: that is what a clobbered signature
    # looks like, and the compiler then parses the body at file scope.
    lines = raw.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = strip_comments_and_strings(line)[0]
        if stripped[:1] and not stripped[:1].isspace() and "(" in stripped:
            depth = stripped.count("(") - stripped.count(")")
            if depth > 0:
                j = i + 1
                while j < len(lines) and depth > 0:
                    nxt = strip_comments_and_strings(lines[j])[0]
                    depth += nxt.count("(") - nxt.count(")")
                    # A ';' on a line that still sits inside the list means
                    # the parameters were replaced by statements; a ';' on
                    # the closing line is just a prototype.
                    if depth > 0 and ";" in nxt:
                        problems.append(
                            "%s:%d: ';' inside the parameter list opened on line %d"
                            % (rel, j + 1, i + 1)
                        )
                        break
                    j += 1
                i = j
                continue
        i += 1
    return problems


def list_deletions(patch_path):
    out = []
    current = None
    for line in open(patch_path, "r", errors="replace"):
        if line.startswith("+++ b/"):
            current = line[6:].strip()
            continue
        if line.startswith("--- ") or line.startswith("@@"):
            continue
        if line.startswith("-") and not line.startswith("---"):
            out.append((current, line[1:].rstrip("\n")))
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    root = sys.argv[1].rstrip("/")
    patch = sys.argv[2] if len(sys.argv) > 2 else None

    if patch:
        files = sorted({line[6:].strip() for line in open(patch, "r", errors="replace")
                        if line.startswith("+++ b/")})
        adds = {}
        cur = None
        for line in open(patch, "r", errors="replace"):
            if line.startswith("+++ b/"):
                cur = line[6:].strip()
            elif line.startswith("+++ "):
                cur = None
            elif cur and line.startswith("+") and not line.startswith("+++"):
                adds[cur] = adds.get(cur, 0) + 1
    else:
        files = sys.argv[1:]
        adds = {}

    pristine = None
    if "--pristine" in sys.argv:
        pristine = sys.argv[sys.argv.index("--pristine") + 1].rstrip("/")

    problems = []
    for rel in files:
        if not rel.endswith(C_SUFFIX):
            continue
        path = root + "/" + rel
        base_path = None
        if pristine:
            candidate = pristine + "/" + rel
            base_path = candidate if os.path.exists(candidate) else None
        try:
            problems.extend(check_file(path, rel, base_path))
        except FileNotFoundError:
            problems.append("%s: missing in the patched tree" % rel)

    print("checked %d C/H file(s) under %s" % (len([f for f in files if f.endswith(C_SUFFIX)]), root))
    if patch:
        dels = list_deletions(patch)
        print("patch: %d added line(s), %d deleted line(s)" % (sum(adds.values()), len(dels)))
        for rel, text in dels:
            print("  deleted in %s: %s" % (rel, text.strip()[:110]))

    if problems:
        print("FAIL")
        for p in problems:
            print("  " + p)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
