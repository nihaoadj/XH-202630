"""Check project declarations, hashed locks and optionally installed versions."""

from __future__ import annotations

import argparse
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]


def read_requirements(path: Path, *, hashed: bool = False) -> list[Requirement]:
    requirements: list[Requirement] = []
    current: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        current.append(line.rstrip("\\").strip())
        if line.endswith("\\"):
            continue
        record = " ".join(current)
        current = []
        requirement = Requirement(record.split("--hash=", 1)[0].strip())
        if hashed and (not str(requirement.specifier).startswith("==") or "--hash=sha256:" not in record):
            raise ValueError(f"Unpinned or unhashed dependency in {path.name}: {requirement.name}")
        if not requirement.marker or requirement.marker.evaluate():
            requirements.append(requirement)
    if current:
        raise ValueError(f"Unterminated dependency record in {path.name}")
    return requirements


def check_group(name: str, *, lock_only: bool) -> list[str]:
    declarations = read_requirements(ROOT / "backend" / f"{name}.txt")
    locked = read_requirements(ROOT / "backend" / f"{name}.lock.txt", hashed=True)
    by_name = {canonicalize_name(item.name): item for item in locked}
    errors: list[str] = []
    for declared in declarations:
        pinned = by_name.get(canonicalize_name(declared.name))
        if pinned is None:
            errors.append(f"{declared.name}: absent from {name}.lock.txt")
            continue
        pinned_version = next(iter(pinned.specifier)).version
        if not declared.specifier.contains(pinned_version, prereleases=True):
            errors.append(f"{declared.name}: locked {pinned_version} violates {declared.specifier}")
    if not lock_only:
        for requirement in locked:
            try:
                installed = metadata.version(requirement.name)
            except metadata.PackageNotFoundError:
                errors.append(f"{requirement.name}: not installed")
                continue
            if not requirement.specifier.contains(installed, prereleases=True):
                errors.append(f"{requirement.name}: installed {installed}, expected {requirement.specifier}")
    print(f"{name}: checked {len(declarations)} declarations and {len(locked)} active locked packages")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock-only", action="store_true", help="Check declarations and locks without inspecting this environment")
    args = parser.parse_args()
    errors = check_group("requirements", lock_only=args.lock_only)
    errors.extend(check_group("requirements-dev", lock_only=args.lock_only))
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
