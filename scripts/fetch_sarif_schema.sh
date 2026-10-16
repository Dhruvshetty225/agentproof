#!/usr/bin/env bash
# Downloads the official SARIF 2.1.0 JSON schema used by tests/test_sarif.py.
#
# The schema is published by OASIS (https://github.com/oasis-tcs/sarif-spec)
# under the OASIS IPR Policy, which is not an open-source license, so it is
# not committed to this repository. It is saved to tests/schemas/ (gitignored).
# The URL is pinned to one commit and the file is checked against a known
# SHA-256 so every run validates against exactly the same schema.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="$ROOT_DIR/tests/schemas/sarif-schema-2.1.0.json"
COMMIT="a560296ca8c921f3bdb8d4a8db57ab83dae968a7"
URL="https://raw.githubusercontent.com/oasis-tcs/sarif-spec/$COMMIT/sarif-2.1/schema/sarif-schema-2.1.0.json"
EXPECTED_SHA256="c3b4bb2d6093897483348925aaa73af03b3e3f4bd4ca38cef26dcb4212a2682e"

mkdir -p "$(dirname "$TARGET")"
curl -sSfL -o "$TARGET.download" "$URL"

if command -v sha256sum >/dev/null 2>&1; then
    ACTUAL_SHA256="$(sha256sum "$TARGET.download" | cut -d' ' -f1)"
else
    ACTUAL_SHA256="$(shasum -a 256 "$TARGET.download" | cut -d' ' -f1)"
fi

if [ "$ACTUAL_SHA256" != "$EXPECTED_SHA256" ]; then
    rm -f "$TARGET.download"
    echo "SARIF schema checksum mismatch: expected $EXPECTED_SHA256, got $ACTUAL_SHA256" >&2
    exit 1
fi

mv "$TARGET.download" "$TARGET"
echo "SARIF 2.1.0 schema saved to $TARGET"
