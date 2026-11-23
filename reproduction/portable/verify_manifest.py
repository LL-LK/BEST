"""Verify the file digests in an extracted portable release."""

import hashlib
import json
from pathlib import Path
import sys


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
    for name, expected in manifest["sha256"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Invalid manifest path {name}")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != expected:
            raise ValueError(f"Checksum mismatch for {name}")
    print(f"Verified {len(manifest['sha256'])} manifest files")


if __name__ == "__main__":
    main()
