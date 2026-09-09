#!/usr/bin/env python3
"""
Diagnóstico de captura de áudio do Baseus Presenter.

Motivo: selecionar o microfone do Baseus no app não capturava nada, enquanto
selecionar "pipewire"/"pulse" aparentemente funcionava. Este script compara
TODOS os caminhos possíveis de captura, medindo o nível real de sinal (RMS),
para descobrir de qual microfone cada opção realmente lê.

Uso:
    # Lista dispositivos (PortAudio) e sources (PipeWire/Pulse)
    python3 tools/diagnose_audio.py list

    # Testa um dispositivo específico com medidor ao vivo
    python3 tools/diagnose_audio.py probe --device 15 --seconds 5

    # Compara todos os caminhos (RECOMENDADO)
    python3 tools/diagnose_audio.py all

No modo "all", FALE CONTINUAMENTE durante todo o teste (e mantenha o botão de
microfone do passador acionado), para que todos os caminhos sejam medidos nas
mesmas condições.
"""
import argparse
import os
import re
import subprocess
import sys
import time

import numpy as np
import sounddevice as sd

# Mesmos parâmetros usados pelo app (app/audio.py)
SAMPLERATE = 16000
BLOCKSIZE = 4000

# Limiares para interpretar o RMS medido
RMS_SINAL_CLARO = 200.0   # acima disso: voz captada sem dúvida
RMS_SILENCIO = 50.0       # abaixo disso: praticamente silêncio digital


# ---------------------------------------------------------------- utilidades

def _hostapi_name(dev):
    try:
        return sd.query_hostapis(dev["hostapi"])["name"]
    except Exception:
        return "?"


def _parse_device(valor):
    """Aceita índice numérico ('15') ou nome ('pulse')."""
    try:
        return int(valor)
    except (TypeError, ValueError):
        return valor


def pactl_sources():
    """Retorna [(nome, estado)] das sources do PipeWire/PulseAudio."""
    try:
        out = subprocess.run(["pactl", "list", "sources", "short"],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return []
    sources = []
    for linha in out.splitlines():
        partes = linha.split("\t")
        if len(partes) >= 2:
            sources.append((partes[1], partes[-1]))
    return sources


def find_baseus_device():
    """Índice do dispositivo PortAudio do Baseus (acesso ALSA direto)."""
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and "baseus" in dev["name"].lower():
            return idx
    return None


def find_baseus_pulse_source():
    """Nome da source PipeWire/Pulse do Baseus."""
    for nome, _estado in pactl_sources():
        if "baseus" in nome.lower():
            return nome
    return None


def find_device_by_name(nome_parcial):
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and nome_parcial == dev["name"].strip().lower():
            return idx
    return None


def app_esta_rodando():
    try:
        out = subprocess.run(["pgrep", "-f", "baseus_app.py"],
                             capture_output=True, text=True).stdout.strip()
        return [l for l in out.splitlines() if l.strip()]
    except Exception:
        return []


def classificar(rms):
    if rms is None:
        return "ERRO"
    if rms >= RMS_SINAL_CLARO:
        return "SINAL CLARO"
    if rms >= RMS_SILENCIO:
        return "sinal fraco"
    return "SILÊNCIO"


# -------------------------------------------------------------------- list

def cmd_list(_args):
    print("=== Dispositivos de ENTRADA vistos pelo PortAudio (sounddevice) ===")
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            marca = "   <-- BASEUS" if "baseus" in dev["name"].lower() else ""
            print(f"  [{idx:>2}] {dev['name']}")
            print(f"       hostapi={_hostapi_name(dev)}  "
                  f"canais={dev['max_input_channels']}  "
                  f"sr_padrao={dev['default_samplerate']:.0f}{marca}")

    print()
    print("=== Sources do PipeWire/PulseAudio (pactl) ===")
    sources = pactl_sources()
    if not sources:
        print("  (pactl indisponível ou nenhuma source)")
    for nome, estado in sources:
        marca = "   <-- BASEUS" if "baseus" in nome.lower() else ""
        print(f"  {nome}  [{estado}]{marca}")

    print()
    print("=== Source PADRÃO do sistema ===")
    try:
        padrao = subprocess.run(["pactl", "get-default-source"],
                                capture_output=True, text=True, timeout=10).stdout.strip()
        print(f"  {padrao}")
        if padrao and "baseus" not in padrao.lower():
            print("  ATENÇÃO: a source padrão NÃO é o Baseus. Abrir 'pulse'/'default'")
            print("           no PortAudio vai capturar deste outro microfone.")
    except Exception as exc:
        print(f"  (não foi possível obter: {exc})")


# ------------------------------------------------------------------- probe

def cmd_probe(args):
    device = _parse_device(args.device)
    blocos = []

    def callback(indata, frames, time_info, status):
        if status:
            print(f"\n  [status PortAudio] {status}", file=sys.stderr)
        blocos.append(bytes(indata))

    try:
        dev_info = sd.query_devices(device)
        print(f"  Dispositivo: {dev_info['name']} (hostapi={_hostapi_name(dev_info)})")
    except Exception as exc:
        print(f"  ERRO ao consultar device {device!r}: {exc}")
        print("RESULT erro=1")
        return 1

    pulse_source = os.environ.get("PULSE_SOURCE")
    print(f"  PULSE_SOURCE={pulse_source if pulse_source else '(não definido)'}")

    try:
        with sd.RawInputStream(samplerate=SAMPLERATE, blocksize=BLOCKSIZE,
                               device=device, dtype="int16", channels=1,
                               callback=callback):
            fim = time.time() + args.seconds
            while time.time() < fim:
                time.sleep(0.1)
                if blocos:
                    arr = np.frombuffer(blocos[-1], dtype=np.int16)
                    if arr.size:
                        rms = float(np.sqrt(np.mean(arr.astype(np.float64) ** 2)))
                        nivel = min(int(rms / 150), 40)
                        barra = "#" * nivel + "." * (40 - nivel)
                        print(f"\r  [{barra}] rms={rms:8.1f}", end="", flush=True)
            print()
    except Exception as exc:
        print(f"\n  ERRO ao abrir/ler o stream: {exc}")
        print("RESULT erro=1")
        return 1

    if not blocos:
        print("  Nenhum bloco de áudio recebido!")
        print("RESULT rms=0.0 max=0 blocos=0")
        return 0

    arr = np.frombuffer(b"".join(blocos), dtype=np.int16).astype(np.float64)
    rms = float(np.sqrt(np.mean(arr ** 2)))
    pico = float(np.max(np.abs(arr))) if arr.size else 0.0
    print(f"RESULT rms={rms:.1f} max={pico:.0f} blocos={len(blocos)}")
    return 0


# --------------------------------------------------------------------- all

def _rodar_probe(device, seconds, pulse_source=None):
    """Roda o probe num SUBPROCESSO (PULSE_SOURCE precisa existir antes do
    PortAudio inicializar, por isso não dá para trocar no mesmo processo)."""
    env = os.environ.copy()
    if pulse_source:
        env["PULSE_SOURCE"] = pulse_source
    else:
        env.pop("PULSE_SOURCE", None)

    cmd = [sys.executable, os.path.abspath(__file__), "probe",
           "--device", str(device), "--seconds", str(seconds)]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0 and proc.stderr.strip():
        sys.stdout.write(proc.stderr)

    m = re.search(r"RESULT rms=([\d.]+) max=(\d+)", proc.stdout)
    if m:
        return float(m.group(1)), int(m.group(2))
    return None, None


def cmd_all(args):
    rodando = app_esta_rodando()
    if rodando:
        print("!" * 70)
        print("O baseus_app.py ESTÁ RODANDO e mantém o microfone aberto:")
        for l in rodando:
            print(f"   {l}")
        print()
        print("Isso IMPEDE o teste de acesso direto ao hardware (hw:) e vai")
        print("falsear os resultados. Feche o app e rode este script de novo:")
        print("   pkill -f baseus_app.py")
        print("!" * 70)
        return 1

    baseus_dev = find_baseus_device()
    baseus_src = find_baseus_pulse_source()
    pulse_dev = find_device_by_name("pulse")
    default_dev = find_device_by_name("default")

    print("=" * 70)
    print("DIAGNÓSTICO DE CAPTURA — Baseus Presenter")
    print("=" * 70)
    print(f"  Device PortAudio do Baseus (ALSA direto): {baseus_dev}")
    print(f"  Source PipeWire do Baseus:                {baseus_src}")
    print(f"  Device 'pulse':                           {pulse_dev}")
    print(f"  Device 'default':                         {default_dev}")
    print()
    print(">>> FALE CONTINUAMENTE durante TODO o teste (~20s).")
    print(">>> Mantenha o botão de microfone do passador ACIONADO.")
    print()
    for i in (3, 2, 1):
        print(f"  começando em {i}...", end="\r", flush=True)
        time.sleep(1)
    print(" " * 30)

    testes = []

    if baseus_dev is not None:
        print(f"[1/4] Baseus via ALSA DIRETO (device={baseus_dev}) "
              "— é o que o app faz ao selecionar o Baseus")
        rms, pico = _rodar_probe(baseus_dev, args.seconds)
        testes.append(("Baseus - ALSA direto (hw:)", rms, pico))
        print()

    if pulse_dev is not None and baseus_src:
        print(f"[2/4] Baseus via PULSE_SOURCE (device=pulse + PULSE_SOURCE)")
        rms, pico = _rodar_probe(pulse_dev, args.seconds, pulse_source=baseus_src)
        testes.append(("Baseus - via PULSE_SOURCE", rms, pico))
        print()

    if pulse_dev is not None:
        print(f"[3/4] 'pulse' SEM PULSE_SOURCE (usa a source PADRÃO do sistema)")
        rms, pico = _rodar_probe(pulse_dev, args.seconds)
        testes.append(("'pulse' (source padrão)", rms, pico))
        print()

    if default_dev is not None:
        print(f"[4/4] 'default' (plugin ALSA padrão)")
        rms, pico = _rodar_probe(default_dev, args.seconds)
        testes.append(("'default'", rms, pico))
        print()

    # ------------------------------------------------------------ resumo
    print("=" * 70)
    print("RESUMO")
    print("=" * 70)
    print(f"  {'caminho':<32} {'RMS':>10} {'pico':>8}   veredito")
    print(f"  {'-'*32} {'-'*10} {'-'*8}   {'-'*12}")
    for nome, rms, pico in testes:
        rms_txt = f"{rms:.1f}" if rms is not None else "erro"
        pico_txt = f"{pico}" if pico is not None else "-"
        print(f"  {nome:<32} {rms_txt:>10} {pico_txt:>8}   {classificar(rms)}")

    print()
    print("=" * 70)
    print("CONCLUSÃO")
    print("=" * 70)

    def get(nome):
        for n, rms, _p in testes:
            if n.startswith(nome):
                return rms
        return None

    direto = get("Baseus - ALSA direto")
    via_pulse_src = get("Baseus - via PULSE_SOURCE")
    pulse_padrao = get("'pulse' (source padrão)")

    if direto is not None and direto >= RMS_SINAL_CLARO:
        print("  O acesso ALSA DIRETO ao Baseus FUNCIONA.")
        print("  => Se o app não transcreve com o Baseus selecionado, o problema")
        print("     NÃO é a captura: investigar o Vosk/estado is_recording.")
    elif via_pulse_src is not None and via_pulse_src >= RMS_SINAL_CLARO:
        print("  O Baseus SÓ funciona via PipeWire (PULSE_SOURCE), não via hw: direto.")
        print("  => CORREÇÃO: o app deve abrir o device 'pulse' definindo")
        print("     PULSE_SOURCE com o nome da source, em vez de abrir hw: direto.")
        print(f"     PULSE_SOURCE={baseus_src}")
    elif pulse_padrao is not None and pulse_padrao >= RMS_SINAL_CLARO:
        print("  Nenhum caminho do BASEUS captou sinal, mas a source PADRÃO captou.")
        print("  => O que 'funcionava' antes era OUTRO microfone (placa-mãe),")
        print("     não o Baseus. O microfone do Baseus não está transmitindo:")
        print("     verificar o botão físico / firmware / pareamento do passador.")
    else:
        print("  NENHUM caminho captou sinal claro.")
        print("  => Ou não houve fala durante o teste, ou o microfone está mudo")
        print("     no hardware. Repita falando alto e com o botão acionado.")


# -------------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(
        description="Diagnóstico de captura de áudio do Baseus Presenter.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="lista dispositivos e sources")
    p_list.set_defaults(func=cmd_list)

    p_probe = sub.add_parser("probe", help="mede o sinal de um dispositivo")
    p_probe.add_argument("--device", required=True,
                         help="índice (ex: 15) ou nome (ex: pulse)")
    p_probe.add_argument("--seconds", type=float, default=5.0)
    p_probe.set_defaults(func=cmd_probe)

    p_all = sub.add_parser("all", help="compara todos os caminhos de captura")
    p_all.add_argument("--seconds", type=float, default=4.0)
    p_all.set_defaults(func=cmd_all)

    args = parser.parse_args()
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
