#!/usr/bin/env bash
# Build a release tarball from the committed HEAD (laptop side).
#   deploy/package.sh   ->  build/thinkballot-<UTC-ts>-<sha>.tgz (+ .sha256)
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -n "$(git status --porcelain)" ]; then
    echo "Refusing to package a dirty working tree. Commit first." >&2
    exit 1
fi
SHA=$(git rev-parse --short HEAD)
RID="$(date -u +%Y%m%dT%H%M%SZ)-$SHA"
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/tbpkg.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT
git archive HEAD | tar -x -C "$STAGE"
rm -rf "$STAGE/mocks" "$STAGE/data/dummy" "$STAGE/tests"   # not needed on the server
printf 'product=thinkballot\nrelease=%s\ncommit=%s\nbuilt_by=%s\nbuilt_at=%s\n' \
    "$RID" "$(git rev-parse HEAD)" "$(git config user.name)" "$(date -u +%FT%TZ)" > "$STAGE/RELEASE"
mkdir -p build
COPYFILE_DISABLE=1 tar --no-xattrs -czf "build/thinkballot-$RID.tgz" -C "$STAGE" .
(cd build && shasum -a 256 "thinkballot-$RID.tgz" > "thinkballot-$RID.tgz.sha256")
echo "build/thinkballot-$RID.tgz"
