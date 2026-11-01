from __future__ import annotations

from pathlib import Path

from src.config import load_config, project_path

CODE_DIRS = ("src/ingest", "src/query")


def directory_list(cfg: dict | None = None) -> list[Path]:
    cfg = cfg or load_config()
    paths = cfg["paths"]
    dirs = [project_path(p) for p in paths.values()]
    dirs.extend(project_path(p) for p in CODE_DIRS)
    return dirs


def create_directories() -> list[Path]:
    created = []
    for path in directory_list():
        path.mkdir(parents=True, exist_ok=True)
        created.append(path)
    return created


def main() -> None:
    created = create_directories()
    print("Phase 1 — directories ready:")
    for path in created:
        print(f"  {path}")


if __name__ == "__main__":
    main()
