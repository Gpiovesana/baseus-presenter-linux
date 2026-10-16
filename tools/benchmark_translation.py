#!/usr/bin/env python3
"""Measure installed Argos models without microphone, downloads or saved speech."""
import argparse
import copy
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=('en', 'es'), default='en')
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 100:
        parser.error('--repeats must be between 1 and 100')
    # Argos' Stanza adapter otherwise refreshes resources.json on first use.
    # Keep this diagnostic offline while retaining the installed inference path.
    import functools
    import stanza
    stanza.Pipeline = functools.partial(stanza.Pipeline, download_method=None)
    from app.audio import AudioThread
    from app.config import Config, DEFAULT_CONFIG
    from app.models import has_translation
    if not has_translation('pt', args.target):
        parser.error('The requested pt translation package is not installed')
    config = Config(copy.deepcopy(DEFAULT_CONFIG))
    config.set_audio('source_lang', 'pt')
    config.set_audio('target_lang', args.target)
    worker = AudioThread(config)
    worker.is_translating = True
    warnings = []
    worker.audio_warning.connect(warnings.append)
    # Fixed synthetic samples only; no user recordings or transcripts.
    samples = ['Bom dia.', 'Hoje vamos estudar o movimento de um objeto.',
               'A velocidade média é calculada dividindo o deslocamento pelo intervalo de tempo.']
    result = {'source': 'pt', 'target': args.target, 'queue_depth': 0,
              'microphone_used': False, 'stanza_resource_refresh': False, 'samples': []}
    for sample in samples:
        durations = []
        for _ in range(args.repeats):
            before = time.perf_counter()
            worker._translate_if_needed(sample)
            durations.append((time.perf_counter() - before) * 1000)
        result['samples'].append({'chars': len(sample), 'duration_ms': durations,
                                  'median_ms': statistics.median(durations), 'max_ms': max(durations)})
    result['failed_calls'] = len(warnings)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(args.output)
    return bool(warnings)


if __name__ == '__main__':
    raise SystemExit(main())
