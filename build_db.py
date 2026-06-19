#!/usr/bin/env python3

import hashlib
import io
import os
import sqlite3
import zipfile
from pathlib import Path

import lxml.etree as ET
from qgztool.util import _celmo

DB = Path(__file__).parent / 'corpus.db'
ROOT = Path(__file__).parent / 'qgxfiles'

# Attributes on <qgis> root that are metadata, not content
CLEANED_REMOVE_ATTRS = {'version', 'savedDateTime', 'author', 'saveUserFull', 'saveUserEmail'}


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def create_schema(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS files (
            id         INTEGER PRIMARY KEY,
            rel_path   TEXT    NOT NULL UNIQUE,
            branch     TEXT,
            filename   TEXT    NOT NULL,
            extension  TEXT    NOT NULL,
            size_bytes INTEGER,
            mtime      REAL,
            sha256     TEXT
        );

        CREATE TABLE IF NOT EXISTS qgs (
            id             INTEGER PRIMARY KEY,
            file_id        INTEGER NOT NULL REFERENCES files(id),
            inner_filename TEXT,
            raw_xml        TEXT NOT NULL,
            celmo_xml      TEXT,
            cleaned_xml    TEXT,
            digest         TEXT,
            line_count     INTEGER
        );
    ''')


def _parse_xml(xml_str):
    parser = ET.XMLParser(remove_blank_text=True)
    return ET.parse(io.StringIO(xml_str), parser)


def _to_c14n_pretty(tree):
    buf = io.BytesIO()
    tree.write_c14n(buf)
    c14n_bytes = buf.getvalue()
    parser = ET.XMLParser(remove_blank_text=True)
    root = ET.fromstring(c14n_bytes, parser)
    return ET.tostring(root, pretty_print=True, encoding='unicode')


def derive_xml_columns(raw_xml):
    try:
        tree = _parse_xml(raw_xml)
        tree = _celmo(tree)
        celmo_xml = _to_c14n_pretty(tree)
    except Exception:
        celmo_xml = None

    try:
        tree = _parse_xml(raw_xml)
        root = tree.getroot()
        for attr in CLEANED_REMOVE_ATTRS:
            root.attrib.pop(attr, None)
        tree = _celmo(tree)
        cleaned_xml = _to_c14n_pretty(tree)
        digest = hashlib.sha256(cleaned_xml.encode()).hexdigest()
        line_count = cleaned_xml.count('\n') + 1
    except Exception:
        cleaned_xml = None
        digest = None
        line_count = None

    return celmo_xml, cleaned_xml, digest, line_count


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
        raw_xml = path.read_text(encoding='utf-8', errors='replace')
        celmo_xml, cleaned_xml, digest, line_count = derive_xml_columns(raw_xml)
        conn.execute(
            '''INSERT INTO qgs
               (file_id, inner_filename, raw_xml, celmo_xml, cleaned_xml, digest, line_count)
               VALUES (?, NULL, ?, ?, ?, ?, ?)''',
            (file_id, raw_xml, celmo_xml, cleaned_xml, digest, line_count),
        )
    elif ext == 'qgz':
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.endswith('.qgs'):
                    raw_xml = zf.read(name).decode('utf-8', errors='replace')
                    celmo_xml, cleaned_xml, digest, line_count = derive_xml_columns(raw_xml)
                    conn.execute(
                        '''INSERT INTO qgs
                           (file_id, inner_filename, raw_xml, celmo_xml, cleaned_xml, digest, line_count)
                           VALUES (?, ?, ?, ?, ?, ?, ?)''',
                        (file_id, name, raw_xml, celmo_xml, cleaned_xml, digest, line_count),
                    )


def main():
    conn = sqlite3.connect(DB)
    create_schema(conn)

    paths = sorted(ROOT.rglob('*.qgs')) + sorted(ROOT.rglob('*.qgz'))
    for i, path in enumerate(paths, 1):
        print(f'[{i}/{len(paths)}] {path.relative_to(ROOT)}')
        process_file(conn, path)

    conn.commit()

    rows = conn.execute('SELECT DISTINCT digest FROM qgs WHERE digest IS NOT NULL').fetchall()
    seen = {}
    collisions = []
    for (digest,) in rows:
        prefix = digest[:4]
        if prefix in seen and seen[prefix] != digest:
            collisions.append((prefix, seen[prefix], digest))
        else:
            seen[prefix] = digest
    if collisions:
        print(f'\nWARNING: {len(collisions)} 4-char prefix collision(s) among distinct digests:')
        for prefix, d1, d2 in collisions:
            print(f'  {prefix}  {d1}  {d2}')
    else:
        print(f'OK: no 4-char prefix collisions among {len(rows)} distinct digests.')

    conn.close()
    print(f'Done. {len(paths)} files indexed into {DB}')


if __name__ == '__main__':
    main()
