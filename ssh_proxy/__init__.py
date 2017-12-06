"""SSH proxy manager"""
import functools
import os
import re
import subprocess

import pkg_resources


def get_version():
    """Return a PEP 440-compliant version number from VERSION."""
    version = get_git_version()
    if version is None:
        try:
            version = pkg_resources.get_distribution(__name__).version
        except ImportError:
            version = 'UNKNOWN'
    return version


@functools.lru_cache()
def get_git_version():
    repo_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isdir(os.path.join(repo_dir, '.git')):
        return
    try:
        describe = subprocess.Popen(
            'git describe --tags --first-parent --dirty --match "v[0-9].*"',
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=True, cwd=repo_dir, universal_newlines=True
        )
        described, _error = describe.communicate()
        if describe.returncode:
            print('Can`t describe version')
            return
        groups = re.match(
            r'^v(?P<tag>[^-\n]*)(?:-(?P<num>\d+)-g(?P<hash>[\da-z]+))?'
            r'(?P<dirty>-dirty)?$',
            described
        )
        dirty = groups['dirty'] or ''
        tag = groups['tag']
        if 'dev' in tag:
            if groups['num'] is not None:
                num = groups['num']
                hash_ = groups['hash']
            else:
                num = 0
                get_hash = subprocess.Popen(
                    'git show --format="%h" --no-patch',
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    shell=True, cwd=repo_dir, universal_newlines=True
                )
                hash_, _error = get_hash.communicate()
                hash_ = hash_.replace('\n', '')
            return f'{tag}{num}+git.{hash_}{dirty}'
        return tag

    except EnvironmentError:
        pass


__version__ = get_version()
