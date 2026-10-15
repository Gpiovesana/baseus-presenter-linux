"""Helpers for the disposable portal cursor probe (no desktop-global inference)."""
import json


def require_metadata_mode(advertised):
    if not advertised & 4:
        raise ValueError('O portal não oferece cursor em metadados; teste não realizado.')
    return 4


def summarize(path):
    result = {'coordinate_space': 'stream; not desktop-global', 'unique_positions': 0,
              'samples': 0, 'malformed_lines': 0, 'buffers': 0,
              'cursor_buffers': 0, 'valid_cursor_buffers': 0}
    positions = set()
    if not path.exists():
        result['missing_log'] = True
        return result
    for line in path.read_text().splitlines():
        try:
            item = json.loads(line)
            if item['event'] == 'cursor' and item.get('id', 0):
                positions.add((item['x'], item['y']))
                result['samples'] += 1
            elif item['event'] == 'stats':
                for key in ('buffers', 'cursor_buffers', 'valid_cursor_buffers'):
                    result[key] = item[key]
            elif item['event'] == 'format':
                result['video_size'] = [item['width'], item['height']]
        except (ValueError, KeyError, TypeError):
            result['malformed_lines'] += 1
    result['unique_positions'] = len(positions)
    return result
