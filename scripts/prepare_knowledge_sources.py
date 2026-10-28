#!/usr/bin/env python3
"""Unified fixed-source preparation and provenance integrity entry point."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import prepare_authoritative_sources as pilot  # noqa: E402
from scripts import expand_authoritative_sources as bulk  # noqa: E402
from scripts import prepare_chinese_sources as chinese  # noqa: E402
from scripts.knowledge_layout import check_layout  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='offline verification, no downloads or writes')
    args = parser.parse_args()
    if (pilot.KB_ROOT / "provenance/evidence-base/manifest.json").is_file():
        if not args.check:
            raise ValueError("active evidence-v2: build a new candidate instead of overwriting source assets")
        from scripts.evidence_corpus_promotion import verify_active
        verify_active(verify_upstream=True)
        return
    if (pilot.KB_ROOT / "provenance/cleaning-base/manifest.json").is_file():
        if not args.check:
            raise ValueError("active cleaned corpus: base preparers cannot overwrite it; use a new candidate")
        from scripts.knowledge_corpus_promotion import verify_active
        verify_active(verify_upstream=True)
        return
    if args.check:
        pilot.check_offline()
        _, raw, sources = bulk.read_catalog()
        bulk.check_offline(raw, sources)
    else:
        pilot.download()
        _, raw, sources = bulk.read_catalog()
        bulk.prepare(raw, sources)
    chinese.prepare(offline=args.check)
    check_layout()


if __name__ == '__main__':
    main()
