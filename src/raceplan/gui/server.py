"""Serve the saved-results explorer on this computer only.

Reading is GET only. Starting, cancelling or watching a comparison is a POST that must come from this page: the Host and Origin
must be this server, the X-RacePlan-Token header must carry the session token, and the body must be a small JSON object.
The token is never in the page or an API answer: it travels only in the #fragment of the address this command opens
or prints (fragments are not sent to servers), so another program that merely fetches the page cannot start a run.
Comparisons run as a separate raceplan.workflow process (see raceplan.gui.jobs)."""
from __future__ import annotations

import argparse
import csv
import hmac
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
import json
from math import isfinite
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import tempfile
import threading
import time
from urllib.parse import parse_qs, quote, urlsplit
import webbrowser

from raceplan.gui.analysis import BadQuery
from raceplan.gui.console import CLOSE_DEADLINE_S, on_console_close
from raceplan.gui.data import Explorer, UnknownItem, _formula_risk, find_runs
from raceplan.gui.frozen import default_results, default_scenarios, is_frozen
from raceplan.gui.jobs import Busy, JobError, Jobs
from raceplan.gui.planner_scan import ScanError, classes as planner_classes

HOST = '127.0.0.1'
PAGE = Path(__file__).parent / 'static/index.html'
TOKEN_FRAGMENT = 'token'
LOAD_ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError, csv.Error)
MAX_BODY = 16 * 1024
DRAIN_LIMIT = 1024 * 1024  # Larger refused bodies are not read; the connection is just closed.
BODY_DEADLINE_S = 5.0  # For the whole body, not per read: a slow sender cannot hold a server thread.
WRITE_TIMEOUT_S = 10.0
JOB_PATH = re.compile(r'/api/jobs/([0-9a-f]{16})')
JOB_POST = re.compile(r'/api/(?:jobs(?:/([0-9a-f]{16})/cancel)?|(watch)(/stop)?|(planner-classes))')


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
            options = {'enabled': False, 'reason': self.server.run_disabled, 'scenarios': [], 'planners': [],
                       'timeout_s': None, 'output_folder': None, 'current_job': None}
        else:
            options = jobs.options()
        return {**options, 'frozen': is_frozen()}  # The packaged exe has no raceplan-run or pip for the page to suggest.

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
                kind, options = url.path.rsplit('/', 1)[1], self._options(url.path, query, multi)
                if 'scope' in multi:
                    # All cases of a suite at once; scope and case are alternatives, never combined.
                    if 'case' in multi or self._single(multi, 'scope') != 'all':
                        raise BadQuery('scope must be all, and scope and case cannot be combined')
                    self._json(HTTPStatus.OK, explorer.compare_all(self._single(multi, 'run'), kind, **options))
                else:
                    self._json(HTTPStatus.OK, explorer.compare(query.get('run', ''), query.get('case', ''), kind, **options))
            elif url.path == '/api/suite/overview':
                if 'case' in multi:
                    raise BadQuery('the overview covers every case; case is not accepted')
                self._json(HTTPStatus.OK, explorer.overview(self._single(multi, 'run')))
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
            elif url.path == '/api/export/suite-episodes.csv':
                if 'case' in multi:
                    raise BadQuery('this export covers every completed case; case is not accepted')
                self._csv(*explorer.export_suite_episodes(self._single(multi, 'run'), self._single(multi, 'filter', 'all')),
                          'episodes.csv')
            elif url.path == '/api/export/coverage.csv':
                if 'case' in multi or 'filter' in multi:
                    raise BadQuery('coverage export covers the whole run; case and filter are not accepted')
                self._csv(*explorer.export_coverage(self._single(multi, 'run')), 'coverage.csv')
            elif url.path == '/api/run-options':
                self._json(HTTPStatus.OK, self._run_options())
            elif url.path == '/api/runs-version':
                self._json(HTTPStatus.OK, {'version': explorer.runs_signature()})
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

    def _read_body(self, length):
        """(body, None), or (None, 'timeout') when the whole body is not in within BODY_DEADLINE_S, or
        (None, 'ended') when the connection ends or breaks before Content-Length bytes."""
        deadline = time.monotonic() + BODY_DEADLINE_S
        chunks, remaining = [], length
        try:
            while remaining > 0:
                left = deadline - time.monotonic()
                if left <= 0:
                    return None, 'timeout'
                self.connection.settimeout(left)
                chunk = self.rfile.read1(min(remaining, 64 * 1024))
                if not chunk:
                    return None, 'ended'
                chunks.append(chunk)
                remaining -= len(chunk)
        except TimeoutError:
            return None, 'timeout'
        except OSError:
            return None, 'ended'
        finally:
            self.connection.settimeout(WRITE_TIMEOUT_S)  # The answer gets its own time, not what was left of the read.
        return b''.join(chunks), None

    def _refuse(self, status, message):
        """Answer a refused POST after reading its (bounded) body: closing a socket with unread bytes makes Windows
        reset the connection, and the client may then lose this answer before reading it."""
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            length = 0
        if 0 < length <= DRAIN_LIMIT:
            self._read_body(length)  # A client that stops sending still gets the answer, or a closed connection.
        self.close_connection = True
        self._json(status, {'error': message})

    def do_POST(self):
        if not self._host_allowed():
            self._refuse(HTTPStatus.FORBIDDEN, 'host not allowed')
            return
        url = urlsplit(self.path)
        route = JOB_POST.fullmatch(url.path)
        if route is None or url.query:
            self._refuse(HTTPStatus.NOT_FOUND, 'not found')
            return
        refused = self._write_allowed()
        if refused:
            self._refuse(*refused)
            return
        try:
            length = int(self.headers.get('Content-Length', ''))
        except ValueError:
            self._refuse(HTTPStatus.LENGTH_REQUIRED, 'Content-Length is required')
            return
        if not 0 <= length <= MAX_BODY:
            self._refuse(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f'body must be at most {MAX_BODY} bytes')
            return
        jobs = self.server.jobs
        if jobs is None:
            self._refuse(HTTPStatus.FORBIDDEN, self.server.run_disabled)
            return
        raw, problem = self._read_body(length) if length else (b'', None)
        if problem:
            self.close_connection = True
            if problem == 'timeout':
                self._json(HTTPStatus.REQUEST_TIMEOUT, {'error': f'the body did not arrive within {BODY_DEADLINE_S:g} s'})
            else:
                self._json(HTTPStatus.BAD_REQUEST, {'error': 'the body ended before its Content-Length'})
            return
        try:
            body = json.loads(raw.decode('utf-8')) if raw else {}
            if route[1]:
                self._json(HTTPStatus.OK, jobs.cancel(route[1]))
            elif route[4]:
                # Parses the file (ast) and lists its planner classes; it is not imported or run.
                if not isinstance(body, dict) or set(body) != {'file'}:
                    raise JobError('give {"file": PATH}')
                self._json(HTTPStatus.OK, planner_classes(body['file']))
            elif route[2] and route[3]:
                self._json(HTTPStatus.OK, {'watch': jobs.stop_watch()})
            elif route[2]:
                self._json(HTTPStatus.ACCEPTED, jobs.watch(body))
            else:
                self._json(HTTPStatus.ACCEPTED, jobs.start(body))
        except (ValueError, UnicodeDecodeError, TypeError) as exc:  # JobError, ScanError, malformed JSON, odd JSON types
            self._json(HTTPStatus.BAD_REQUEST,
                       {'error': str(exc) if isinstance(exc, (JobError, ScanError)) else 'body must be valid JSON'})
        except Busy as exc:
            self._json(HTTPStatus.CONFLICT, {'error': str(exc)})
        except KeyError:
            self._json(HTTPStatus.NOT_FOUND, {'error': 'unknown job'})
        except OSError as exc:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {'error': f'could not start the comparison: {exc}'})


class ExplorerServer(ThreadingHTTPServer):
    """On Windows SO_REUSEADDR (http.server's default) lets another socket bind this same address and port and receive
    this page's requests, token included; exclusive use refuses that. On POSIX it only allows a quick restart."""
    allow_reuse_address = os.name != 'nt'

    def server_bind(self):
        if os.name == 'nt':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(root, port=0, scenarios=None, run_timeout=900.0, run_off_reason='running comparisons is off'):
    """Without a scenarios folder the server only reads saved results."""
    server = ExplorerServer((HOST, port), Handler)
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


def explorer_url(server, run_name=None, all_cases=False):
    """The address to open: run selection in the query, the session token only in the fragment. A suite opens on
    all of its cases together, as when it is picked from the list."""
    url = f'http://{HOST}:{server.server_address[1]}/'
    if run_name:
        url += '?run=' + quote(run_name) + ('&scope=all' if all_cases else '')
    return url + f'#{TOKEN_FRAGMENT}=' + server.token


def open_browser(url):
    """Open the explorer; returns a launcher file to remove at exit, if one was made. On Linux and macOS the browser
    launcher (xdg-open, open) gets the address as a command-line argument other accounts can read, so it gets a private
    (0600) local file that forwards to the address instead, removed after a minute or at exit. Windows does not show
    other accounts' command lines, so it opens the address. A failure only means opening the printed address by hand."""
    if os.name == 'nt':
        webbrowser.open(url)
        return None
    name = None
    try:
        descriptor, name = tempfile.mkstemp(prefix='raceplan-open-', suffix='.html')
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(f'<!doctype html><meta charset="utf-8"><title>RacePlan Explorer</title>'
                         f'<script>location.replace({json.dumps(url)})</script><a href="{html.escape(url)}">RacePlan Explorer</a>')
        webbrowser.open(Path(name).as_uri())
    except OSError as exc:
        print(f'could not open a browser ({exc}); open the explorer= address above', flush=True)
    if name:
        remover = threading.Timer(60, lambda: Path(name).unlink(missing_ok=True))
        remover.daemon = True
        remover.start()
    return name


def _stop_on_signal(*_):
    raise KeyboardInterrupt  # Closing the terminal or SIGTERM still runs the cleanup that stops started comparisons.


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('path', type=Path, nargs='?',
                        help=f'folder holding saved runs, or one saved workflow/suite folder '
                             f'(default: {default_results()}, created if missing)')
    parser.add_argument('--port', type=int, default=0, help='local port; defaults to any free port')
    parser.add_argument('--no-browser', action='store_true', help='print the address without opening a browser')
    parser.add_argument('--scenarios', type=Path, default=default_scenarios(),
                        help='scenario folder offered for new comparisons; running is off when it does not exist '
                             '(default: %(default)s)')
    parser.add_argument('--no-run', action='store_true', help='only read saved results; never start comparisons')
    parser.add_argument('--run-timeout', type=float, default=900.0, help='seconds before a started comparison is stopped')
    args = parser.parse_args(argv)
    if args.path is None:
        # The default folder is where new runs go, so a first start with no results yet still opens the explorer.
        args.path = default_results()
        if not args.path.exists():
            try:
                args.path.mkdir(parents=True)
            except OSError as exc:
                parser.error(f'could not create {args.path}: {exc}')
            print(f'created empty results folder: {args.path.resolve()}', flush=True)
    path = args.path.resolve()
    if not path.is_dir():
        parser.error(f'not a folder: {args.path}')  # A folder you named yourself is never created: it may be a typo.
    if not isfinite(args.run_timeout) or args.run_timeout <= 0:
        parser.error('run timeout must be a positive number of seconds')
    is_run = path in find_runs(path)
    try:
        server = make_server(path.parent if is_run else path, args.port, None if args.no_run else args.scenarios,
                             args.run_timeout, 'running comparisons is off (--no-run)')
    except OSError as exc:
        hint = ('; a previous explorer may still hold this port for a moment: wait, or leave out --port to use any free port'
                if args.port else '')
        parser.error(f'{exc}{hint}')
    url = explorer_url(server, path.name if is_run else None, is_run and (path / 'suite.json').is_file())
    print(f'explorer={url}', flush=True)
    print(f'results={server.explorer.root}', flush=True)
    print(f'run={"on, scenarios=" + str(server.jobs.scenarios) if server.jobs else "off: " + server.run_disabled}', flush=True)
    for name in ('SIGTERM', 'SIGHUP', 'SIGBREAK'):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _stop_on_signal)
    remove_close_handler = on_console_close(lambda: server.jobs.shutdown(deadline_s=CLOSE_DEADLINE_S)) if server.jobs else None
    launcher = None if args.no_browser else open_browser(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if server.jobs:
            server.jobs.shutdown()
        if remove_close_handler:
            remove_close_handler()
        server.server_close()
        if launcher:
            Path(launcher).unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
