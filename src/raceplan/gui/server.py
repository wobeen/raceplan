"""Serve the saved-results explorer on this computer only.

Reading is GET only. Starting or cancelling a comparison is a POST that must come from this page: the Host and Origin
must be this server, the X-RacePlan-Token header must carry the session token, and the body must be a small JSON object.
The token is never in the page or an API answer: it travels only in the #fragment of the address this command opens
or prints (fragments are not sent to servers), so another program that merely fetches the page cannot start a run.
Comparisons run as a separate raceplan.workflow process (see raceplan.gui.jobs)."""
from __future__ import annotations

import argparse
import csv
import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
import json
from math import isfinite
from pathlib import Path
import re
import secrets
import signal
from urllib.parse import parse_qs, quote, urlsplit
import webbrowser

from raceplan.gui.analysis import BadQuery
from raceplan.gui.data import Explorer, UnknownItem, _formula_risk, find_runs
from raceplan.gui.jobs import Busy, JobError, Jobs

HOST = '127.0.0.1'
PAGE = Path(__file__).parent / 'static/index.html'
TOKEN_FRAGMENT = 'token'
LOAD_ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError, csv.Error)
MAX_BODY = 16 * 1024
JOB_PATH = re.compile(r'/api/jobs/([0-9a-f]{16})')
JOB_POST = re.compile(r'/api/jobs(?:/([0-9a-f]{16})/cancel)?')


class Handler(BaseHTTPRequestHandler):
    server_version = 'RacePlanExplorer'

    def log_message(self, format, *args):
        pass

    def _send(self, status, body, content_type, headers=()):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, value):
        self._send(status, json.dumps(value, allow_nan=False, ensure_ascii=False).encode('utf-8'),
                   'application/json; charset=utf-8')

    def _csv(self, rows, name, fallback):
        """UTF-8 with BOM (Excel reads Korean) and CRLF records; cells are written as saved, never rewritten.
        Cells a spreadsheet could run as formulas are flagged for the page to warn about, not altered."""
        stream = StringIO()
        csv.writer(stream, lineterminator='\r\n').writerows(rows)
        headers = [('Content-Disposition', f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}")]
        if _formula_risk(rows):
            headers.append(('X-RacePlan-CSV-Formula-Risk', '1'))
        self._send(HTTPStatus.OK, ('\ufeff' + stream.getvalue()).encode('utf-8'), 'text/csv; charset=utf-8', headers)

    def _host_allowed(self):
        # Rejecting other Host values stops a remote page reaching this server through DNS rebinding.
        port = self.server.server_address[1]
        return self.headers.get('Host') in {f'{HOST}:{port}', f'localhost:{port}'}

    def _write_allowed(self):
        """A cross-site page can send a simple POST here, but it cannot set this Origin or read the page's token."""
        port = self.server.server_address[1]
        if self.headers.get('Origin') not in {f'http://{HOST}:{port}', f'http://localhost:{port}'}:
            return HTTPStatus.FORBIDDEN, 'origin not allowed'
        token = self.headers.get('X-RacePlan-Token', '')
        if not hmac.compare_digest(token.encode('utf-8', 'replace'), self.server.token.encode()):
            return HTTPStatus.FORBIDDEN, 'missing or wrong session token'
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            return HTTPStatus.UNSUPPORTED_MEDIA_TYPE, 'body must be application/json'
        return None

    def _run_options(self):
        jobs = self.server.jobs
        if jobs is None:
            return {'enabled': False, 'reason': self.server.run_disabled, 'scenarios': [], 'planners': [],
                    'timeout_s': None, 'output_folder': None, 'current_job': None}
        return jobs.options()

    @staticmethod
    def _single(multi, key, default=None):
        """Exports name exactly what they contain: a key given twice or left blank is rejected, not guessed."""
        values = multi.get(key)
        if values is None and default is not None:
            return default
        if values is None or len(values) != 1 or not values[0]:
            raise BadQuery(f'{key} must be given once and must not be empty')
        return values[0]

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
            elif url.path == '/api/export/episodes.csv':
                self._csv(*explorer.export_episodes(self._single(multi, 'run'), self._single(multi, 'case'),
                                                    self._single(multi, 'filter', 'all')), 'episodes.csv')
            elif url.path == '/api/export/coverage.csv':
                if 'case' in multi or 'filter' in multi:
                    raise BadQuery('coverage export covers the whole run; case and filter are not accepted')
                self._csv(*explorer.export_coverage(self._single(multi, 'run')), 'coverage.csv')
            elif url.path == '/api/run-options':
                self._json(HTTPStatus.OK, self._run_options())
            elif JOB_PATH.fullmatch(url.path):
                if self.server.jobs is None:
                    raise UnknownItem('running comparisons is off')
                try:
                    self._json(HTTPStatus.OK, self.server.jobs.get(JOB_PATH.fullmatch(url.path)[1]))
                except KeyError:
                    raise UnknownItem('unknown job') from None
            else:
                self._json(HTTPStatus.NOT_FOUND, {'error': 'not found'})
        except BadQuery as exc:
            self._json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
        except UnknownItem as exc:
            self._json(HTTPStatus.NOT_FOUND, {'error': str(exc)})
        except LOAD_ERRORS as exc:
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {'error': str(exc)})

    def do_POST(self):
        if not self._host_allowed():
            self._json(HTTPStatus.FORBIDDEN, {'error': 'host not allowed'})
            return
        url = urlsplit(self.path)
        route = JOB_POST.fullmatch(url.path)
        if route is None or url.query:
            self._json(HTTPStatus.NOT_FOUND, {'error': 'not found'})
            return
        refused = self._write_allowed()
        if refused:
            self._json(refused[0], {'error': refused[1]})
            return
        try:
            length = int(self.headers.get('Content-Length', ''))
        except ValueError:
            self._json(HTTPStatus.LENGTH_REQUIRED, {'error': 'Content-Length is required'})
            return
        if not 0 <= length <= MAX_BODY:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {'error': f'body must be at most {MAX_BODY} bytes'})
            return
        jobs = self.server.jobs
        if jobs is None:
            self._json(HTTPStatus.FORBIDDEN, {'error': self.server.run_disabled})
            return
        try:
            body = json.loads(self.rfile.read(length).decode('utf-8')) if length else {}
            if route[1]:
                self._json(HTTPStatus.OK, jobs.cancel(route[1]))
            else:
                self._json(HTTPStatus.ACCEPTED, jobs.start(body))
        except (ValueError, UnicodeDecodeError, TypeError) as exc:  # JobError, malformed JSON, odd JSON types
            self._json(HTTPStatus.BAD_REQUEST, {'error': str(exc) if isinstance(exc, JobError) else 'body must be valid JSON'})
        except Busy as exc:
            self._json(HTTPStatus.CONFLICT, {'error': str(exc)})
        except KeyError:
            self._json(HTTPStatus.NOT_FOUND, {'error': 'unknown job'})
        except OSError as exc:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {'error': f'could not start the comparison: {exc}'})


def make_server(root, port=0, scenarios=None, run_timeout=900.0, run_off_reason='running comparisons is off'):
    """Without a scenarios folder the server only reads saved results."""
    server = ThreadingHTTPServer((HOST, port), Handler)
    server.explorer = Explorer(root)
    server.token = secrets.token_urlsafe(32)
    server.jobs, server.run_disabled = None, run_off_reason
    if scenarios is not None:
        folder = Path(scenarios).resolve()
        if folder.is_dir():
            server.jobs = Jobs(server.explorer.root, folder, run_timeout)
        else:
            server.run_disabled = f'scenarios folder not found: {folder}'
    return server


def explorer_url(server, run_name=None):
    """The address to open: run selection in the query, the session token only in the fragment."""
    url = f'http://{HOST}:{server.server_address[1]}/'
    if run_name:
        url += '?run=' + quote(run_name)
    return url + f'#{TOKEN_FRAGMENT}=' + server.token


def _stop_on_signal(*_):
    raise KeyboardInterrupt  # Closing the terminal or SIGTERM still runs the cleanup that stops started comparisons.


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('path', type=Path, nargs='?', default=Path('results/raw'),
                        help='folder holding saved runs, or one saved workflow/suite folder')
    parser.add_argument('--port', type=int, default=0, help='local port; defaults to any free port')
    parser.add_argument('--no-browser', action='store_true', help='print the address without opening a browser')
    parser.add_argument('--scenarios', type=Path, default=Path('scenarios'),
                        help='scenario folder offered for new comparisons; running is off when it does not exist')
    parser.add_argument('--no-run', action='store_true', help='only read saved results; never start comparisons')
    parser.add_argument('--run-timeout', type=float, default=900.0, help='seconds before a started comparison is stopped')
    args = parser.parse_args(argv)
    path = args.path.resolve()
    if not path.is_dir():
        parser.error(f'not a folder: {args.path}')
    if not isfinite(args.run_timeout) or args.run_timeout <= 0:
        parser.error('run timeout must be a positive number of seconds')
    is_run = path in find_runs(path)
    try:
        server = make_server(path.parent if is_run else path, args.port, None if args.no_run else args.scenarios,
                             args.run_timeout, 'running comparisons is off (--no-run)')
    except OSError as exc:
        parser.error(str(exc))
    url = explorer_url(server, path.name if is_run else None)
    print(f'explorer={url}', flush=True)
    print(f'run={"on, scenarios=" + str(server.jobs.scenarios) if server.jobs else "off: " + server.run_disabled}', flush=True)
    for name in ('SIGTERM', 'SIGHUP', 'SIGBREAK'):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _stop_on_signal)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if server.jobs:
            server.jobs.shutdown()
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
