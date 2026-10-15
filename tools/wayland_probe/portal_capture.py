#!/usr/bin/env python3
"""Disposable ScreenCast portal/PipeWire probe; never saves screen pixels.

Use system Python with Gio and GStreamer introspection. Authorization is always
interactive. --preview shows the authorized stream for feedback-loop inspection.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid


class PortalCancelled(Exception):
    pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=20)
    parser.add_argument('--preview', action='store_true')
    parser.add_argument('--cursor-metadata', action='store_true', help='Use native PipeWire cursor reader, without video preview')
    parser.add_argument('--cursor-reader', type=Path, default=Path('/tmp/baseus-cursor-reader'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 300:
        parser.error('--seconds must be between 1 and 300')
    if args.cursor_metadata and args.preview:
        parser.error('--cursor-metadata does not support --preview')
    report = {'timestamp_utc': datetime.now(timezone.utc).isoformat(),
              'session_type': os.environ.get('XDG_SESSION_TYPE', ''),
              'desktop': os.environ.get('XDG_CURRENT_DESKTOP', ''),
              'status': 'not-started', 'frames': 0, 'streams': [],
              'session_closed_by_portal': False,
              'feedback_loop': 'not-tested', 'end_to_end_latency_ms': 'not-measured'}
    connection = None
    session = None
    subscriptions = []
    pipelines = []
    fds = []
    readers = []
    reader_logs = []
    try:
        import gi
        gi.require_version('Gst', '1.0')
        from gi.repository import Gio, GLib, Gst
        Gst.init(None)
        if not args.cursor_metadata and Gst.ElementFactory.find('pipewiresrc') is None:
            raise RuntimeError('GStreamer pipewiresrc is unavailable; install the probe dependency gstreamer1.0-pipewire')
        if args.cursor_metadata and not os.access(args.cursor_reader, os.X_OK):
            raise RuntimeError('Leitor de cursor ausente. Compile cursor_reader.c antes do teste.')
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        destination = 'org.freedesktop.portal.Desktop'
        desktop_path = '/org/freedesktop/portal/desktop'
        interface = 'org.freedesktop.portal.ScreenCast'
        sender = connection.get_unique_name().lstrip(':').replace('.', '_')
        loop = GLib.MainLoop()
        def call(path, iface, method, parameters):
            return connection.call_sync(destination, path, iface, method, parameters,
                                        None, Gio.DBusCallFlags.NONE, 10000, None)
        def close_request(path):
            try:
                call(path, 'org.freedesktop.portal.Request', 'Close', None)
            except GLib.Error:
                pass
        def request(method, signature, prefix, options):
            token = 'baseus_' + uuid.uuid4().hex
            request_path = f'/org/freedesktop/portal/desktop/request/{sender}/{token}'
            options = dict(options, handle_token=GLib.Variant('s', token))
            result = []
            waiting = GLib.MainLoop()
            def response(conn, sender_name, path, iface, name, parameters, user_data):
                result.append(parameters.unpack())
                waiting.quit()
            subscription = connection.signal_subscribe(
                destination, 'org.freedesktop.portal.Request', 'Response', request_path,
                None, Gio.DBusSignalFlags.NONE, response, None)
            expired = []
            def expire():
                expired.append(True)
                waiting.quit()
                return False
            timeout = GLib.timeout_add_seconds(60, expire)
            try:
                handle = call(desktop_path, interface, method,
                              GLib.Variant(signature, (*prefix, options))).unpack()[0]
                if handle != request_path:
                    close_request(handle)
                    raise RuntimeError('Portal returned an unexpected request path')
                waiting.run()
                if not result:
                    raise TimeoutError(f'{method}: response timeout')
                code, values = result[0]
                report.setdefault('responses', []).append({'method': method, 'code': code})
                if code == 1:
                    raise PortalCancelled(method)
                if code != 0:
                    raise RuntimeError(f'{method}: portal response {code}')
                return values
            finally:
                if not expired:
                    GLib.source_remove(timeout)
                connection.signal_unsubscribe(subscription)
                if not result:
                    close_request(request_path)
        def closed(conn, sender_name, path, iface, name, parameters, user_data):
            report['session_closed_by_portal'] = True
            loop.quit()
        # Predict the session path so even a CreateSession timeout is cleaned up.
        session_token = 'baseus_' + uuid.uuid4().hex
        session = f'/org/freedesktop/portal/desktop/session/{sender}/{session_token}'
        subscriptions.append(connection.signal_subscribe(
            destination, 'org.freedesktop.portal.Session', 'Closed', session,
            None, Gio.DBusSignalFlags.NONE, closed, None))
        created = request('CreateSession', '(a{sv})', (),
                          {'session_handle_token': GLib.Variant('s', session_token)})
        if created['session_handle'] != session:
            # Retain the returned handle for cleanup even on unexpected portals.
            session = created['session_handle']
            raise RuntimeError('Portal returned an unexpected session path')
        options = {'types': GLib.Variant('u', 1), 'multiple': GLib.Variant('b', True)}
        if args.cursor_metadata:
            from cursor_support import require_metadata_mode
            properties = call(desktop_path, 'org.freedesktop.DBus.Properties', 'Get',
                              GLib.Variant('(ss)', (interface, 'AvailableCursorModes'))).unpack()
            advertised = properties[0]
            report['available_cursor_modes'] = advertised
            options['cursor_mode'] = GLib.Variant('u', require_metadata_mode(advertised))
            report['requested_cursor_mode'] = 'metadata'
        request('SelectSources', '(oa{sv})', (session,), options)
        started = request('Start', '(osa{sv})', (session, ''), {})
        streams = started.get('streams', [])
        if not streams:
            raise RuntimeError('Portal authorized no streams')
        report['streams'] = [{'node': node, 'properties': properties} for node, properties in streams]
        authorized_at = time.perf_counter()
        report['authorized_monotonic_ms'] = time.monotonic() * 1000
        def handoff(sink, buffer, pad):
            report['frames'] += 1
            if 'first_frame_after_authorization_ms' not in report:
                report['first_frame_after_authorization_ms'] = (time.perf_counter() - authorized_at) * 1000
        def message(bus, event):
            if event.type == Gst.MessageType.ERROR:
                error, debug = event.parse_error()
                report['pipeline_error'] = str(error)
                loop.quit()
            elif event.type == Gst.MessageType.EOS:
                report['pipeline_eos'] = True
                loop.quit()
        for node, properties in streams:
            reply, fd_list = connection.call_with_unix_fd_list_sync(
                destination, desktop_path, interface, 'OpenPipeWireRemote',
                GLib.Variant('(oa{sv})', (session, {})), None,
                Gio.DBusCallFlags.NONE, 10000, None, None)
            fd = fd_list.get(reply.unpack()[0])
            fds.append(fd)
            if args.cursor_metadata:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                log_path = args.output.with_name(f'{args.output.stem}-node-{node}.jsonl')
                error_path = log_path.with_suffix('.stderr.txt')
                with log_path.open('w') as output, error_path.open('w') as errors:
                    child = subprocess.Popen([str(args.cursor_reader), str(fd), str(node)],
                                             pass_fds=(fd,), stdout=output, stderr=errors)
                readers.append(child)
                reader_logs.append((node, log_path, error_path))
                print(f'Cursor: monitor/stream {node}; registro em {log_path}', flush=True)
                continue
            # Node IDs are the backwards-compatible API. Each probe session is
            # short-lived; any Closed/EOS/error stops it rather than reconnecting.
            description = (f'pipewiresrc fd={fd} path={node} do-timestamp=true ! '
                           'queue max-size-buffers=2 leaky=downstream ! ')
            if args.preview:
                description += 'tee name=t t. ! queue ! videoconvert ! autovideosink sync=false t. ! queue ! '
            description += 'fakesink name=measure sync=false signal-handoffs=true'
            pipeline = Gst.parse_launch(description)
            pipelines.append(pipeline)
            pipeline.get_by_name('measure').connect('handoff', handoff)
            bus = pipeline.get_bus()
            bus.add_signal_watch()
            bus.connect('message', message)
            if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
                raise RuntimeError('GStreamer failed to start')
        def monitor_readers():
            if any(child.poll() is not None for child in readers):
                report['cursor_reader_ended_early'] = True
                loop.quit()
                return False
            return True
        if readers:
            GLib.timeout_add(250, monitor_readers)
            print('Captura autorizada. Agora teste o cursor sobre o Okular nativo em apresentação e nos dois monitores.', flush=True)
        report['status'] = 'streaming'
        GLib.timeout_add_seconds(args.seconds, lambda: (loop.quit(), False)[1])
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda: (loop.quit(), False)[1])
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: (loop.quit(), False)[1])
        if not report['session_closed_by_portal']:
            loop.run()
        report['capture_seconds'] = time.perf_counter() - authorized_at
        report['status'] = 'error' if report.get('pipeline_error') else 'ended'
    except PortalCancelled:
        report['status'] = 'cancelled'
    except (Exception, KeyboardInterrupt) as exc:
        report['status'] = 'error'
        report['error'] = str(exc)
    finally:
        for child in readers:
            if child.poll() is None:
                child.terminate()
        for child in readers:
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        if readers:
            from cursor_support import summarize
            report['cursor_streams'] = []
            for child, (node, log_path, error_path) in zip(readers, reader_logs):
                result = summarize(log_path)
                result.update(node=node, log=str(log_path), exit_code=child.returncode,
                              errors=error_path.read_text()[-2000:])
                report['cursor_streams'].append(result)
                print(f"Stream {node}: {result['unique_positions']} posições distintas; "
                      f"{result['valid_cursor_buffers']} buffers com cursor válido.", flush=True)
            report['frames'] = sum(item['buffers'] for item in report['cursor_streams'])
            if any(child.returncode != 0 for child in readers) or report.get('cursor_reader_ended_early'):
                report['status'] = 'error'
        for pipeline in pipelines:
            pipeline.set_state(Gst.State.NULL)
            pipeline.get_bus().remove_signal_watch()
        for fd in fds:
            os.close(fd)
        if connection and session:
            try:
                connection.call_sync('org.freedesktop.portal.Desktop', session,
                                     'org.freedesktop.portal.Session', 'Close', None,
                                     None, Gio.DBusCallFlags.NONE, 5000, None)
                report['session_close_requested'] = True
            except Exception as exc:
                report['session_close_error'] = str(exc)
        if connection:
            for subscription in subscriptions:
                connection.signal_unsubscribe(subscription)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        print(args.output)
    return 1 if report['status'] == 'error' else 0


if __name__ == '__main__':
    raise SystemExit(main())
