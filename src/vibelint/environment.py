"""What actually exists: the standard library, installed packages, declared deps.

Deciding that an import is hallucinated is a strong claim, so this module is
deliberately generous. An import is only called a ghost when it is absent from
*every* source of truth we can consult. If a package is merely declared but not
installed, that is the user's setup, not the model's invention, and we say so.
"""

from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Set

# Python 3.10+ exposes this directly; 3.9 needs a bundled list.
_STDLIB_FALLBACK = frozenset(
    """
    __future__ _thread abc aifc argparse array ast asynchat asyncio asyncore atexit
    audioop base64 bdb binascii binhex bisect builtins bz2 calendar cgi cgitb chunk
    cmath cmd code codecs codeop collections colorsys compileall concurrent configparser
    contextlib contextvars copy copyreg crypt csv ctypes curses dataclasses datetime dbm
    decimal difflib dis distutils doctest email encodings ensurepip enum errno faulthandler
    fcntl filecmp fileinput fnmatch fractions ftplib functools gc genericpath getopt getpass
    gettext glob graphlib grp gzip hashlib heapq hmac html http imaplib imghdr imp importlib
    inspect io ipaddress itertools json keyword lib2to3 linecache locale logging lzma
    mailbox mailcap marshal math mimetypes mmap modulefinder msilib msvcrt multiprocessing
    netrc nis nntplib ntpath nturl2path numbers operator optparse os ossaudiodev parser
    pathlib pdb pickle pickletools pipes pkgutil platform plistlib poplib posix posixpath
    pprint profile pstats pty pwd py_compile pyclbr pydoc queue quopri random re readline
    reprlib resource rlcompleter runpy sched secrets select selectors shelve shlex shutil
    signal site smtpd smtplib sndhdr socket socketserver spwd sqlite3 sre_compile
    sre_constants sre_parse ssl stat statistics string stringprep struct subprocess sunau
    symbol symtable sys sysconfig syslog tabnanny tarfile telnetlib tempfile termios test
    textwrap threading time timeit tkinter token tokenize trace traceback tracemalloc tty
    turtle turtledemo types typing unicodedata unittest urllib uu uuid venv warnings wave
    weakref webbrowser winreg winsound wsgiref xdrlib xml xmlrpc zipapp zipfile zipimport
    zlib zoneinfo
    """.split()
)

#: Distributions whose install name differs from what you actually import.
#: Without these, `import yaml` looks hallucinated when PyYAML is declared.
DISTRIBUTION_ALIASES: Dict[str, str] = {
    "pyyaml": "yaml",
    "beautifulsoup4": "bs4",
    "pillow": "PIL",
    "python-dateutil": "dateutil",
    "python-dotenv": "dotenv",
    "msgpack-python": "msgpack",
    "attrs": "attr",
    "protobuf": "google",
    "scikit-learn": "sklearn",
    "scikit-image": "skimage",
    "opencv-python": "cv2",
    "opencv-python-headless": "cv2",
    "pycryptodome": "Crypto",
    "python-magic": "magic",
    "pytest-cov": "pytest_cov",
    "typing-extensions": "typing_extensions",
    "google-auth": "google",
    "google-cloud-storage": "google",
    "grpcio": "grpc",
    "psycopg2-binary": "psycopg2",
    "mysqlclient": "MySQLdb",
    "python-jose": "jose",
    "pyjwt": "jwt",
    "faker": "faker",
    "setuptools": "setuptools",
    "nvidia-ml-py": "pynvml",
    "azure-storage-blob": "azure",
    "discord-py": "discord",
    "python-telegram-bot": "telegram",
    "pymupdf": "fitz",
    "sqlalchemy": "sqlalchemy",
}


@lru_cache(maxsize=1)
def stdlib_modules() -> Set[str]:
    """Top-level module names shipped with this Python."""
    names = getattr(sys, "stdlib_module_names", None)
    if names:
        return set(names)
    return set(_STDLIB_FALLBACK)


@lru_cache(maxsize=1)
def installed_top_level() -> Set[str]:
    """Top-level import names provided by installed distributions."""
    names: Set[str] = set()

    try:
        from importlib import metadata
    except ImportError:  # pragma: no cover - Python < 3.8
        return names

    # Python 3.10+: a direct import-name -> distribution mapping.
    mapping = getattr(metadata, "packages_distributions", None)
    if mapping is not None:
        try:
            names.update(mapping().keys())
        except Exception:  # noqa: VC030
            # Deliberate: a broken distribution in site-packages must not stop
            # the scan. The loop below re-derives the same names another way.
            pass

    # Older Pythons, and anything the mapping missed: read each distribution.
    try:
        distributions = list(metadata.distributions())
    except Exception:
        distributions = []

    for dist in distributions:
        try:
            top_level = dist.read_text("top_level.txt")
        except Exception:
            top_level = None

        if top_level:
            names.update(line.strip() for line in top_level.splitlines() if line.strip())
            continue

        # Fall back to inferring from the installed file list.
        try:
            files = dist.files or []
        except Exception:
            files = []
        for file in files:
            parts = Path(str(file)).parts
            if not parts or parts[0].endswith((".dist-info", ".egg-info")):
                continue
            head = parts[0]
            if head.endswith(".py"):
                names.add(head[:-3])
            elif "." not in head:
                names.add(head)

    return {name for name in names if name and not name.startswith("_vendor")}


@lru_cache(maxsize=None)
def module_is_importable(name: str) -> bool:
    """Last-resort check for modules installed outside package metadata.

    Only ever called with a top-level name, which `find_spec` can resolve
    without executing the module's code.
    """
    try:
        import importlib.util

        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, ModuleNotFoundError, AttributeError):
        return False
    except Exception:
        return False


# -- declared dependencies ----------------------------------------------

_REQUIREMENT_LINE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def normalize_distribution(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def declared_dependencies(root: Path) -> Set[str]:
    """Import names implied by the project's declared dependencies.

    A package listed in requirements.txt but not installed is a setup problem,
    not a hallucination, and must not be reported as one.
    """
    declared: Set[str] = set()

    for candidate in _dependency_files(root):
        try:
            text = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # noqa: VC030
            # Deliberate: an unreadable requirements file just means we learn
            # nothing from it, which is a smaller problem than refusing to run.
            continue

        if candidate.name == "pyproject.toml":
            declared.update(_parse_pyproject(text))
        else:
            declared.update(_parse_requirements(text))

    # Expand each distribution name into the name you would actually import.
    expanded: Set[str] = set()
    for dist in declared:
        normalized = normalize_distribution(dist)
        expanded.add(DISTRIBUTION_ALIASES.get(normalized, normalized.replace("-", "_")))
        expanded.add(normalized.replace("-", "_"))
        expanded.add(normalized.replace("-", ""))
    return expanded


def _dependency_files(root: Path):
    if root.is_file():
        root = root.parent

    names = [
        "requirements.txt",
        "requirements-dev.txt",
        "requirements_dev.txt",
        "dev-requirements.txt",
        "pyproject.toml",
        "Pipfile",
        "setup.py",
        "constraints.txt",
    ]

    # Look in the target directory and a couple of levels up, since people run
    # vibelint on a subdirectory of a larger project.
    seen = set()
    for base in [root, *list(root.parents)[:2]]:
        for name in names:
            path = base / name
            if path.is_file() and path not in seen:
                seen.add(path)
                yield path

    for path in root.glob("requirements/*.txt"):
        if path not in seen:
            seen.add(path)
            yield path


def _parse_requirements(text: str) -> Set[str]:
    found = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-r", "--", "-e", "http", "git+")):
            continue
        match = _REQUIREMENT_LINE.match(line)
        if match:
            found.add(match.group(1))
    return found


def _parse_pyproject(text: str) -> Set[str]:
    """Pull dependency names out of pyproject.toml.

    Uses tomllib where available and falls back to a line scan, because
    dependency extraction must not be the thing that crashes the run.
    """
    found: Set[str] = set()

    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            tomllib = None  # type: ignore

    if tomllib is not None:
        try:
            data = tomllib.loads(text)
        except Exception:
            data = None

        if isinstance(data, dict):
            project = data.get("project", {})
            for entry in project.get("dependencies", []) or []:
                match = _REQUIREMENT_LINE.match(str(entry))
                if match:
                    found.add(match.group(1))
            for group in (project.get("optional-dependencies", {}) or {}).values():
                for entry in group or []:
                    match = _REQUIREMENT_LINE.match(str(entry))
                    if match:
                        found.add(match.group(1))

            poetry = (
                data.get("tool", {}).get("poetry", {}).get("dependencies", {}) or {}
            )
            found.update(str(key) for key in poetry if str(key).lower() != "python")

            if found:
                return found

    # Text fallback: catch quoted requirement strings anywhere in the file.
    for match in re.finditer(r"[\"']([A-Za-z0-9][A-Za-z0-9._-]{1,})\s*(?:[<>=!~\[].*?)?[\"']", text):
        found.add(match.group(1))
    return found


def known_import_names(root: Path) -> Set[str]:
    """Everything an import could legitimately refer to, outside the project."""
    return stdlib_modules() | installed_top_level() | declared_dependencies(root)
