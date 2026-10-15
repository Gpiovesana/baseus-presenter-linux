"""Versioned installation procedure receipt; this is not a hardware health check.

Standalone (stdlib only) so both shell scripts can use system Python. Revisions
are exact contracts, not ordered capability levels: a newer procedure need not
be compatible with an older one.
"""
import argparse
import json
import os
from pathlib import Path
import tempfile


class RequirementsError(ValueError):
    pass


def read_contract(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise RequirementsError('Missing or invalid system requirements record') from exc
    if (not isinstance(value, dict) or set(value) != {'schema', 'revision'}
            or type(value['schema']) is not int or value['schema'] != 1
            or type(value['revision']) is not int or value['revision'] < 1):
        raise RequirementsError('Unknown system requirements contract')
    return value


def check(manifest, installation):
    required = read_contract(manifest)
    applied = read_contract(Path(installation) / '.system-requirements.json')
    if required != applied:
        raise RequirementsError('Incompatible system requirements')


def record(manifest, installation, applied_revision):
    required = read_contract(manifest)
    if required['revision'] != applied_revision:
        raise RequirementsError('Installer did not apply the required revision')
    destination = Path(installation) / '.system-requirements.json'
    fd, temporary = tempfile.mkstemp(prefix='.system-requirements-', dir=destination.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(required, stream, sort_keys=True)
            stream.write('\n')
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'record', 'validate'))
    parser.add_argument('manifest')
    parser.add_argument('installation')
    parser.add_argument('--applied-revision', type=int)
    args = parser.parse_args()
    try:
        if args.action == 'check':
            check(args.manifest, args.installation)
        elif args.action == 'record':
            record(args.manifest, args.installation, args.applied_revision)
        elif read_contract(args.manifest)['revision'] != args.applied_revision:
            raise RequirementsError('Installer cannot apply this revision')
    except RequirementsError as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
