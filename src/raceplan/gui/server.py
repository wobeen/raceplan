"""Serve the saved-results explorer on this computer only."""
from __future__ import annotations

import argparse
import csv
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit
import webbrowser

from raceplan.gui.analysis import BadQuery
from raceplan.gui.data import Explorer, UnknownItem, find_runs

HOST = '127.0.0.1'
PAGE = Path(__file__).parent / 'static/index.html'
LOAD_ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError, csv.Error)


class Handler(BaseHTTPRequestHandler):
    server_version = 'RacePlanExplorer'

    def log_message(self, format, *args):
        pass

    def _send(self, status, body, content_type):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, value):
        self._send(status, json.dumps(value, allow_nan=False, ensure_ascii=False).encode('utf-8'),
                   'application/json; charset=utf-8')

    def _host_allowed(self):
        # Rejecting other Host values stops a remote page reaching this server through DNS rebinding.
        port = self.server.server_address[1]
        return self.headers.get('Host') in {f'{HOST}:{port}', f'localhost:{port}'}

    @staticmethod
    def _options(path, query, multi):
        """Filters repeat their key per value (names may contain commas). An absent key means no filter;
        a key with only blank values selects nothing."""
        def listed(key, convert=str):
            return None if key not in multi else [convert(item) for item in multi[key] if item]

        try:
            options = {'planners': listed('planners'), 'seeds': listed('seeds', int), 'outcomes': listed('outcomes')}
        except ValueError:
            raise BadQuery('seeds must be integers') from None
        options['metric' if path.endswith('delta') else 'x'] = query.get('metric' if path.endswith('delta') else 'x')
        return {key: value for key, value in options.items() if value is not None}

    def do_GET(self):
        if not self._host_allowed():
            self._json(HTTPStatus.FORBIDDEN, {'error': 'host not allowed'})
            return
        url = urlsplit(self.path)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        multi = parse_qs(url.query, keep_blank_values=True)
        explorer = self.server.explorer
        try:
            if url.path == '/':
                self._send(HTTPStatus.OK, PAGE.read_bytes(), 'text/html; charset=utf-8')
            elif url.path == '/api/runs':
                self._json(HTTPStatus.OK, {'root': str(explorer.root), 'runs': explorer.runs()})
            elif url.path == '/api/run':
                self._json(HTTPStatus.OK, explorer.run(query.get('id', '')))
            elif url.path == '/api/case':
                self._json(HTTPStatus.OK, explorer.case(query.get('run', ''), query.get('id', '')))
            elif url.path in ('/api/compare/delta', '/api/compare/scatter'):
                self._json(HTTPStatus.OK, explorer.compare(query.get('run', ''), query.get('case', ''),
                                                           url.path.rsplit('/', 1)[1], **self._options(url.path, query, multi)))
            elif url.path == '/api/compare/replay':
                try:
                    seed = int(query.get('seed', ''))
                except ValueError:
                    raise BadQuery('seed must be an integer') from None
                self._json(HTTPStatus.OK, explorer.replay(query.get('run', ''), query.get('case', ''),
                                                          query.get('a', ''), query.get('b', ''), seed))
            else:
                self._json(HTTPStatus.NOT_FOUND, {'error': 'not found'})
        except BadQuery as exc:
            self._json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
        except UnknownItem as exc:
            self._json(HTTPStatus.NOT_FOUND, {'error': str(exc)})
        except LOAD_ERRORS as exc:
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {'error': str(exc)})


def make_server(root, port=0):
    server = ThreadingHTTPServer((HOST, port), Handler)
    server.explorer = Explorer(root)
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('path', type=Path, nargs='?', default=Path('results/raw'),
                        help='folder holding saved runs, or one saved workflow/suite folder')
    parser.add_argument('--port', type=int, default=0, help='local port; defaults to any free port')
    parser.add_argument('--no-browser', action='store_true', help='print the address without opening a browser')
    args = parser.parse_args(argv)
    path = args.path.resolve()
    if not path.is_dir():
        parser.error(f'not a folder: {args.path}')
    is_run = path in find_runs(path)
    try:
        server = make_server(path.parent if is_run else path, args.port)
    except OSError as exc:
        parser.error(str(exc))
    url = f'http://{HOST}:{server.server_address[1]}/'
    if is_run:
        url += '?run=' + quote(path.name)
    print(f'explorer={url}', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
