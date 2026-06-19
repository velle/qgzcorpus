#!/usr/bin/env python3

import hashlib
import os
import sqlite3
import zipfile
from pathlib import Path

DB = Path(__file__).parent / 'corpus.db'
ROOT = Path(__file__).parent / 'qgxfiles'


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def create_schema(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS files (
            id        INTEGER PRIMARY KEY,
            rel_path  TEXT    NOT NULL UNIQUE,
            branch    TEXT,
            filename  TEXT    NOT NULL,
            extension TEXT    NOT NULL,
            size_bytes INTEGER,
            mtime     REAL,
            sha256    TEXT
        );

        CREATE TABLE IF NOT EXISTS qgs (
            id             INTEGER PRIMARY KEY,
            file_id        INTEGER NOT NULL REFERENCES files(id),
            inner_filename TEXT,
            xml            TEXT    NOT NULL
        );
    ''')


def infer_branch(rel_path):
    parts = Path(rel_path).parts
    if len(parts) >= 2 and parts[0] == 'qgis_branches':
        return parts[1]
    return None


def process_file(conn, path):
    rel_path = str(path.relative_to(ROOT))
    ext = path.suffix.lstrip('.')
    stat = path.stat()

    file_id = conn.execute(
        '''INSERT OR IGNORE INTO files
           (rel_path, branch, filename, extension, size_bytes, mtime, sha256)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (
            rel_path,
            infer_branch(rel_path),
            path.name,
            ext,
            stat.st_size,
            stat.st_mtime,
            sha256(path),
        ),
    ).lastrowid

    if file_id == 0:
        file_id = conn.execute(
            'SELECT id FROM files WHERE rel_path = ?', (rel_path,)
        ).fetchone()[0]

    if ext == 'qgs':
        xml = path.read_text(encoding='utf-8', errors='replace')
        conn.execute(
            'INSERT INTO qgs (file_id, inner_filename, xml) VALUES (?, NULL, ?)',
            (file_id, xml),
        )
    elif ext == 'qgz':
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.endswith('.qgs'):
                    xml = zf.read(name).decode('utf-8', errors='replace')
                    conn.execute(
                        'INSERT INTO qgs (file_id, inner_filename, xml) VALUES (?, ?, ?)',
                        (file_id, name, xml),
                    )


def main():
    conn = sqlite3.connect(DB)
    create_schema(conn)

    paths = sorted(ROOT.rglob('*.qgs')) + sorted(ROOT.rglob('*.qgz'))
    for i, path in enumerate(paths, 1):
        print(f'[{i}/{len(paths)}] {path.relative_to(ROOT)}')
        process_file(conn, path)

    conn.commit()
    conn.close()
    print(f'\nDone. {len(paths)} files indexed into {DB}')


if __name__ == '__main__':
    main()
