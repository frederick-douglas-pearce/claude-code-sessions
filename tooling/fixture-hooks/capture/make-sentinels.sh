#!/usr/bin/env bash
# Write every #295 and #303 sentinel file into the current directory, each holding its
# own name, so the visible result of a Read shows which file was actually read.
# Rerun to reset after a session (S3's rm step can delete one).
set -euo pipefail

for name in \
  plain-1.txt p1.txt p2.txt p3.txt p4.txt explore.txt \
  allow.txt ask.txt rewrite.txt rewrite-target.txt forbidden.txt \
  denied-by-rule.txt slow.txt crash.txt \
  forbidden-http-1.txt forbidden-http-2.txt forbidden-http-3.txt \
  forbidden-http-4.txt forbidden-http-5.txt \
  forbidden-2.txt crash-open.txt badschema.txt raise-closed.txt deadline-closed.txt exit2.txt \
  rewrite-unknown-key.txt rewrite-invalid.txt \
  missing-script.txt missing-exe.txt missing-exe-block.txt \
  svc-1.txt svc-2.txt svc-3.txt svc-4.txt prompt-control.txt prompt-timeout.txt
do
  printf 'sentinel: %s\n' "$name" > "$name"
done
echo "sentinels written"
