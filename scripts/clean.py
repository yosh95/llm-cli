import shutil
from pathlib import Path


def clean() -> None:
    """Remove temporary files and directories."""
    patterns = [
        ".ruff_cache",
        ".pytest_cache",
        ".mypy_cache",
        ".coverage",
        "htmlcov",
        "build",
        "dist",
        "*.egg-info",
        "**/__pycache__",
        "**/*.py[co]",
        "**/*$py.class",
    ]

    root = Path()
    for pattern in patterns:
        # Path.glob doesn't support recursive=True like glob.glob,
        # but the patterns themselves have ** which Path.glob handles.
        for path in root.glob(pattern):
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                    print(f"Removed directory: {path}")
                else:
                    path.unlink()
                    print(f"Removed file: {path}")
            except Exception as e:
                print(f"Error removing {path}: {e}")


if __name__ == "__main__":
    clean()
