from git import Repo
from pathlib import Path
import argparse
import os
import shutil

parser = argparse.ArgumentParser(description='Collect .qgs/.qgz files from QGIS repo branches')
parser.add_argument('repo', help='Path to the QGIS repository clone')
args = parser.parse_args()

REPO = args.repo
DST = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'qgxfiles/qgis_branches')
TESTDATA = os.path.join(REPO, 'tests/testdata')
BRANCHES = [
    'release-3_0',
    'release-3_4',
    'release-3_10',
    'release-3_16',
    'release-3_22',
    'release-3_28',
    'release-3_34',
    'master',
]

if os.path.exists(DST):
    shutil.rmtree(DST)

repo = Repo.init(REPO)
for branch in BRANCHES:
    print('#BRANCH', branch)
    repo.git.checkout(branch)
    os.makedirs(os.path.join(DST, branch), exist_ok=True)

    for path in Path(TESTDATA).rglob('*.qgz'):
        relpath = os.path.relpath(path, TESTDATA)
        print('  -', relpath)
        dst = os.path.join(DST, branch, relpath)
        os.makedirs(Path(dst).parent, exist_ok=True)
        shutil.copyfile(path, dst)

    for path in Path(TESTDATA).rglob('*.qgs'):
        relpath = os.path.relpath(path, TESTDATA)
        print('  -', relpath)
        dst = os.path.join(DST, branch, relpath)
        os.makedirs(Path(dst).parent, exist_ok=True)
        shutil.copyfile(path, dst)
