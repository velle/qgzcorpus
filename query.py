#!/usr/bin/env python3

import argparse
import io
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import lxml.etree as ET

DB = Path(__file__).parent / 'corpus.db'


def create_schema(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS xpath_queries (
            id          INTEGER PRIMARY KEY,
            expression  TEXT NOT NULL,
            ran_at      TEXT NOT NULL,
            file_count  INTEGER,
            match_count INTEGER
        );
        CREATE TABLE IF NOT EXISTS xpath_results (
            id          INTEGER PRIMARY KEY,
            query_id    INTEGER NOT NULL REFERENCES xpath_queries(id),
            qgs_id      INTEGER NOT NULL REFERENCES qgs(id),
            file_id     INTEGER NOT NULL REFERENCES files(id),
            branch      TEXT,
            struct_path TEXT,
            lxml_path   TEXT,
            xml         TEXT
        );
    ''')


def struct_path(element):
    parts = []
    node = element
    while node is not None and isinstance(node, ET._Element):
        parts.append(node.tag)
        node = node.getparent()
    parts.reverse()
    return '/' + '/'.join(parts)


def run_query(expression, conn):
    rows = conn.execute('''
        SELECT q.id, q.file_id, f.branch, f.filename, q.cleaned_xml
        FROM qgs q
        JOIN files f ON f.id = q.file_id
        WHERE q.cleaned_xml IS NOT NULL
        ORDER BY f.branch, f.filename
    ''').fetchall()

    # Remove previous results for the same expression
    old = conn.execute(
        'SELECT id FROM xpath_queries WHERE expression = ?', (expression,)
    ).fetchall()
    for (old_id,) in old:
        conn.execute('DELETE FROM xpath_results WHERE query_id = ?', (old_id,))
        conn.execute('DELETE FROM xpath_queries WHERE id = ?', (old_id,))

    query_id = conn.execute(
        'INSERT INTO xpath_queries (expression, ran_at, file_count, match_count) VALUES (?, ?, 0, 0)',
        (expression, datetime.now(timezone.utc).isoformat()),
    ).lastrowid

    total_matches = 0
    files_with_matches = 0
    parser = ET.XMLParser(remove_blank_text=True)

    for i, (qgs_id, file_id, branch, filename, cleaned_xml) in enumerate(rows, 1):
        print(f'\r  {i}/{len(rows)}', end='', flush=True)
        try:
            tree = ET.parse(io.StringIO(cleaned_xml), parser)
            matches = tree.xpath(expression)
        except ET.XPathEvalError as e:
            print(f'\nXPath error: {e}')
            return None
        except ET.XMLSyntaxError:
            continue

        if not matches:
            continue

        files_with_matches += 1
        total_matches += len(matches)

        for match in matches:
            if isinstance(match, ET._Element):
                sp = struct_path(match)
                lp = tree.getpath(match)
                xml = ET.tostring(match, pretty_print=True, encoding='unicode')
            else:
                sp = None
                lp = None
                xml = str(match)

            conn.execute(
                '''INSERT INTO xpath_results
                   (query_id, qgs_id, file_id, branch, struct_path, lxml_path, xml)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (query_id, qgs_id, file_id, branch, sp, lp, xml),
            )

    print()
    conn.execute(
        'UPDATE xpath_queries SET file_count=?, match_count=? WHERE id=?',
        (files_with_matches, total_matches, query_id),
    )
    conn.commit()
    return query_id


def print_report(query_id, conn):
    q = conn.execute(
        'SELECT expression, ran_at, file_count, match_count FROM xpath_queries WHERE id=?',
        (query_id,),
    ).fetchone()
    if not q:
        print(f'No query with id={query_id}')
        return

    expression, ran_at, file_count, match_count = q
    total_files = conn.execute(
        'SELECT COUNT(*) FROM qgs WHERE cleaned_xml IS NOT NULL'
    ).fetchone()[0]

    print(f'\nXPath:         {expression}')
    print(f'Ran at:        {ran_at}')
    print(f'Files matched: {file_count} / {total_files}')
    print(f'Total matches: {match_count}')

    paths = conn.execute(
        '''SELECT struct_path, COUNT(*) as n
           FROM xpath_results WHERE query_id=? AND struct_path IS NOT NULL
           GROUP BY struct_path ORDER BY n DESC''',
        (query_id,),
    ).fetchall()
    if paths:
        print('\nStructural paths:')
        for path, count in paths:
            print(f'  {count:5d}  {path}')

    branches = conn.execute(
        '''SELECT branch, COUNT(*) as n
           FROM xpath_results WHERE query_id=?
           GROUP BY branch ORDER BY branch''',
        (query_id,),
    ).fetchall()
    if branches:
        print('\nPer branch (matched):')
        for branch, count in branches:
            print(f'  {count:5d}  {branch}')

    no_match = conn.execute(
        '''SELECT f.branch, f.filename, f.rel_path
           FROM qgs q
           JOIN files f ON f.id = q.file_id
           WHERE q.cleaned_xml IS NOT NULL
           AND q.file_id NOT IN (
               SELECT DISTINCT file_id FROM xpath_results WHERE query_id = ?
           )
           ORDER BY f.branch, f.filename''',
        (query_id,),
    ).fetchall()
    if no_match:
        print(f'\nFiles without matches ({len(no_match)}):')
        for branch, filename, rel_path in no_match:
            print(f'  [{branch}]  {filename}')


def list_queries(conn):
    rows = conn.execute(
        'SELECT id, expression, ran_at, file_count, match_count FROM xpath_queries ORDER BY ran_at DESC'
    ).fetchall()
    if not rows:
        print('No stored queries.')
        return
    print(f'{"ID":>4}  {"files":>6}  {"matches":>8}  expression')
    print('-' * 60)
    for qid, expr, ran_at, fc, mc in rows:
        print(f'{qid:>4}  {fc or 0:>6}  {mc or 0:>8}  {expr}')


def main():
    parser = argparse.ArgumentParser(
        description='Run XPath query against corpus and store results.'
    )
    sub = parser.add_subparsers(dest='cmd')

    run_p = sub.add_parser('run', help='Run an XPath expression')
    run_p.add_argument('expression')

    show_p = sub.add_parser('show', help='Show report for a stored query')
    show_p.add_argument('query_id', type=int)

    sub.add_parser('list', help='List all stored queries')

    args = parser.parse_args()

    conn = sqlite3.connect(DB)
    create_schema(conn)

    if args.cmd == 'run':
        print(f'Running: {args.expression}')
        qid = run_query(args.expression, conn)
        if qid:
            print_report(qid, conn)
    elif args.cmd == 'show':
        print_report(args.query_id, conn)
    elif args.cmd == 'list':
        list_queries(conn)
    else:
        parser.print_help()

    conn.close()


if __name__ == '__main__':
    main()
