#!/usr/bin/env python3
"""Check a repository environment's pip requirements using its own Python."""
import importlib.metadata
from pathlib import Path
import re
import subprocess
import sys

from pip._vendor.packaging.requirements import Requirement


def pip_requirements(source):
    """Read the simple pip lists used by env/*.yml; reject unsupported entries."""
    requirements = []
    indentation = None
    for line in source.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = re.fullmatch(r'(\s*)-\s+pip:\s*(?:#.*)?', line)
        if match:
            indentation = len(match[1])
            continue
        if indentation is None:
            continue
        if len(line) - len(line.lstrip()) <= indentation:
            indentation = None
            continue
        match = re.fullmatch(r'\s*-\s+([^#]+?)(?:\s+#.*)?', line)
        if not match:
            raise ValueError('Unsupported pip requirement entry: ' + line)
        requirement = Requirement(match[1].strip())
        if requirement.url:
            raise ValueError('URL pip requirements need an explicit verification policy')
        requirements.append(requirement)
    return requirements


def requirement_errors(requirements, version=importlib.metadata.version):
    errors = []
    for requirement in requirements:
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            installed = version(requirement.name)
        except importlib.metadata.PackageNotFoundError:
            errors.append('Missing pip package: ' + str(requirement))
            continue
        if not requirement.specifier.contains(installed, prereleases=True):
            errors.append(f'Pip version mismatch: {requirement}; installed {installed}')
    return errors


def main():
    try:
        requirements = pip_requirements(Path(sys.argv[1]).read_text())
        errors = requirement_errors(requirements)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 1
    # Metadata alone misses broken transitive dependencies. Use the target pip.
    return subprocess.run([sys.executable, '-m', 'pip', 'check']).returncode


if __name__ == '__main__':
    sys.exit(main())
