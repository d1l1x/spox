# spox

Spox is a Python 3 project scaffold that depends on `ib_async` and `ta-lib`.

## Installation

The project is packaged with a modern `pyproject.toml`, so you can install it directly with pip:

```bash
pip install .
```

To install directly from a VCS URL (for example, GitHub):

```bash
pip install git+https://github.com/your-org/spox.git
```

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .[dev]
```

## Notes on dependencies

- `ib_async` is specified as a core runtime dependency.
- `ta-lib` requires native TA-Lib libraries on many platforms. Install the system library first (e.g., `brew install ta-lib` on macOS or the appropriate package for your distro) before running `pip install .`.

## Usage

The package currently contains a minimal module export to allow extension:

```python
from spox import __version__

print(__version__)
```
