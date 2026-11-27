#!/bin/sh
# Public-tree gate: run in the repository root before a push, and in the release workflow on every tag.
# Fails on files that must never be public, and on text that marks a private copy (the old icon manifest named the
# SolidWorks program file it was taken from and said "Do not share"). Exit 0 = clean.
set -u
cd "$(git rev-parse --show-toplevel)" || exit 2
FAIL=0
BAD=$(git ls-files | grep -E 'NOT-FOR-DISTRIBUTION|\.lck$|(^|/)\.~\$|\.(exe|dll|so|AppImage|sldprt|sldasm|slddrw)$|__pycache__|\.pyc$|^swstyle/resources/icons/manifest\.json$' || true)
if [ -n "$BAD" ]; then echo "Files that must not ship:"; echo "$BAD"; FAIL=1; fi
MARK=$(git ls-files -z | grep -zvE '^(\.github/check-public-tree\.sh|\.gitignore)$' \
  | xargs -0 grep -IlE 'swStyle[A-Za-z]*\.dll|SolidWorksStyleIconCopy|Do not share|NOT-FOR-DISTRIBUTION' 2>/dev/null || true)
if [ -n "$MARK" ]; then echo "Files with private-copy markers (SolidWorks DLL path, 'Do not share', ...):"; echo "$MARK"; FAIL=1; fi
[ "$FAIL" = 0 ] && echo "public tree check: clean"
exit "$FAIL"
