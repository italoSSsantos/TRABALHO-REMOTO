#!/usr/bin/env python3
"""
AudioLink - leva o microfone do notebook para o PC remoto, em tempo real.

No PC o audio recebido e tocado no "CABLE Input" (VB-Cable), de modo que
qualquer programa (Teams, softphone, discador, Meet) possa selecionar
"CABLE Output" como microfone e ouvir voce normalmente.

Uso tipico:
    NOTEBOOK:  python audiolink.py send --to 192.168.0.50
    PC:        python audiolink.py recv

Ver dispositivos:
    python audiolink.py list
"""

import argparse
import hashlib
import socket
import struct
import sys
import threading
import time
from collections import deque

import numpy as np
import sounddevice as sd

# ---------------------------------------------------------------- protocolo

MAGIC = b"AL01"
HEADER = struct.Struct("<4s4sI")  # magic, token, seq
SAMPLERATE = 48000
BLOCK = 480                       # 10 ms por pacote
DTYPE = "int16"
DEFAULT_PORT = 50505
DISCOVERY_PORT = 50506           # onde o PC anuncia que esta pronto
BEACON = b"ALHI"                 # "estou aqui, sou um PC recebendo"


def token_of(secret):
    """4 bytes derivados do segredo, so para descartar trafego estranho."""
    return hashlib.sha256(secret.encode("utf-8")).digest()[:4]


# ------------------------------------------------------------- dispositivos

def wasapi_index():
    for i, h in enumerate(sd.query_hostapis()):
        if h["name"] == "Windows WASAPI":
            return i
    return None


def extra_settings(device_index):
    """auto_convert deixa o WASAPI reamostrar sozinho se o device nao estiver a 48k."""
    try:
        if sd.query_devices(device_index)["hostapi"] == wasapi_index():
            return sd.WasapiSettings(auto_convert=True)
    except Exception:
        pass
    return None


def find_device(spec, kind):
    """Resolve um device por indice, por trecho do nome, ou o padrao do sistema."""
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    devices = sd.query_devices()

    if spec is None:
        # prefere o padrao do WASAPI: o do MME funciona, mas com ~100ms de latencia
        wasapi = wasapi_index()
        if wasapi is not None:
            field = "default_input_device" if kind == "input" else "default_output_device"
            idx = sd.query_hostapis(wasapi).get(field, -1)
            if idx is not None and idx >= 0 and devices[idx][key] > 0:
                return int(idx)
        idx = sd.default.device[0 if kind == "input" else 1]
        if idx is None or idx < 0:
            raise RuntimeError("Nenhum dispositivo de " + kind + " padrao no Windows.")
        return int(idx)

    if isinstance(spec, str) and spec.isdigit():
        spec = int(spec)
    if isinstance(spec, int):
        if devices[spec][key] < 1:
            raise RuntimeError("Device {} nao serve como {}.".format(spec, kind))
        return spec

    needle = spec.lower()
    hits = [i for i, d in enumerate(devices)
            if needle in d["name"].lower() and d[key] > 0]
    if not hits:
        raise RuntimeError(
            'Nao achei nenhum dispositivo de {} com "{}".\n'
            "Rode  python audiolink.py list  para ver os nomes.".format(kind, spec)
        )
    # prefere WASAPI (menor latencia e nomes completos)
    wasapi = wasapi_index()
    for i in hits:
        if devices[i]["hostapi"] == wasapi:
            return i
    return hits[0]


def describe(idx):
    d = sd.query_devices(idx)
    api = sd.query_hostapis(d["hostapi"])["name"]
    return "[{}] {}  ({})".format(idx, d["name"], api)


def cmd_list():
    wasapi = wasapi_index()
    print("\n=== ENTRADAS (microfones) ===")
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            mark = " *" if d["hostapi"] == wasapi else "  "
            api = sd.query_hostapis(d["hostapi"])["name"]
            print("{}{:3d}  {}  ({})".format(mark, i, d["name"], api))

    print("\n=== SAIDAS (alto-falantes / cabos virtuais) ===")
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] > 0:
            mark = " *" if d["hostapi"] == wasapi else "  "
            api = sd.query_hostapis(d["hostapi"])["name"]
            print("{}{:3d}  {}  ({})".format(mark, i, d["name"], api))

    print("\n* = WASAPI (preferir estes)\n")

    has_cable = any("cable input" in d["name"].lower() for d in sd.query_devices())
    if has_cable:
        print('VB-Cable encontrado. Esta maquina pode rodar o modo "recv".')
    else:
        print('VB-Cable NAO encontrado ("CABLE Input" nao existe).')
        print("Se esta e a maquina que vai RECEBER o microfone, instale o VB-Cable:")
        print("   https://vb-audio.com/Cable/")


# ---------------------------------------------------------- jitter buffer

class JitterBuffer:
    """Absorve a variacao de chegada dos pacotes sem deixar a latencia crescer."""

    def __init__(self, target_blocks, max_blocks):
        self.q = deque()
        self.lock = threading.Lock()
        self.target = target_blocks
        self.max = max_blocks
        self.filling = True
        self.underruns = 0
        self.dropped = 0

    def push(self, block):
        with self.lock:
            self.q.append(block)
            while len(self.q) > self.max:
                self.q.popleft()
                self.dropped += 1
            if self.filling and len(self.q) >= self.target:
                self.filling = False

    def pop(self):
        """Retorna um bloco, ou None quando deve tocar silencio."""
        with self.lock:
            if self.filling or not self.q:
                if not self.filling:
                    self.underruns += 1
                    self.filling = True   # re-enche antes de voltar a tocar
                return None
            return self.q.popleft()

    def depth(self):
        with self.lock:
            return len(self.q)


def dica_taxa():
    return (
        "\n  Esse dispositivo pode nao aceitar {} Hz."
        "\n  Tente outro --hz (16000 / 24000 / 48000), ou escolha um"
        "\n  dispositivo WASAPI de:  python audiolink.py list"
    ).format(SAMPLERATE)


# ------------------------------------------------------------------ envio

class Sender:
    """Captura um device de entrada e manda em UDP para o peer."""

    def __init__(self, sock, device, peer_ref, token, stats):
        self.sock = sock
        self.device = device
        self.peer_ref = peer_ref      # lista de 1 item: (ip, porta) ou None
        self.token = token
        self.stats = stats
        self.seq = 0
        self.channels = 1
        self.stream = None

    def _callback(self, indata, frames, time_info, status):
        peer = self.peer_ref[0]
        if peer is None:
            return
        if self.channels == 1:
            mono = indata[:, 0]
        else:
            mono = indata.mean(axis=1).astype(np.int16)
        buf = np.ascontiguousarray(mono).tobytes()
        pkt = HEADER.pack(MAGIC, self.token, self.seq & 0xFFFFFFFF) + buf
        self.seq += 1
        try:
            self.sock.sendto(pkt, peer)
        except OSError:
            return
        self.stats["tx"] += 1
        self.stats["level"] = float(np.abs(mono).max()) / 32768.0

    def start(self):
        info = sd.query_devices(self.device)
        last = None
        for ch in (1, min(2, info["max_input_channels"])):
            if ch < 1:
                continue
            try:
                self.channels = ch
                self.stream = sd.InputStream(
                    device=self.device, channels=ch, samplerate=SAMPLERATE,
                    dtype=DTYPE, blocksize=BLOCK, latency="low",
                    extra_settings=extra_settings(self.device),
                    callback=self._callback,
                )
                self.stream.start()
                return
            except Exception as e:
                last = e
        raise RuntimeError("Nao consegui abrir a entrada {}:\n  {}{}".format(
            describe(self.device), last, dica_taxa()))

    def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()


# ---------------------------------------------------------------- recepcao

class Receiver:
    """Le o socket, enfileira no jitter buffer e toca num device de saida."""

    def __init__(self, sock, device, token, stats, jitter_ms, learn_peer=None):
        self.sock = sock
        self.device = device
        self.token = token
        self.stats = stats
        self.learn_peer = learn_peer   # lista de 1 item, se deve aprender quem falou
        target = max(1, jitter_ms // 10)
        self.jb = JitterBuffer(target_blocks=target, max_blocks=target * 4)
        self.channels = 1
        self.stream = None
        self.running = True
        self.last_seq = None
        self.warned_rate = False

    def _callback(self, outdata, frames, time_info, status):
        block = self.jb.pop()
        if block is None or len(block) != frames:
            outdata.fill(0)
            return
        for c in range(self.channels):
            outdata[:, c] = block

    def _net_loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if len(data) < HEADER.size:
                continue
            magic, tok, seq = HEADER.unpack_from(data)
            if magic != MAGIC or tok != self.token:
                self.stats["rejected"] += 1
                continue
            if len(data) - HEADER.size != BLOCK * 2:
                if not self.warned_rate:
                    self.warned_rate = True
                    outro = (len(data) - HEADER.size) // 2 * 100
                    print("\n  ATENCAO: o outro lado esta em {} Hz e este em {} Hz."
                          "\n  Use o mesmo --hz nos dois lados.\n".format(outro, SAMPLERATE))
                continue
            if self.learn_peer is not None and self.learn_peer[0] != addr:
                self.learn_peer[0] = addr
                print("\n  peer conectado: {}:{}".format(addr[0], addr[1]))
            if self.last_seq is not None:
                gap = (seq - self.last_seq) & 0xFFFFFFFF
                if 1 < gap < 1000:
                    self.stats["lost"] += gap - 1
            self.last_seq = seq
            block = np.frombuffer(data, dtype=np.int16, offset=HEADER.size).copy()
            self.jb.push(block)
            self.stats["rx"] += 1

    def start(self):
        info = sd.query_devices(self.device)
        last = None
        opened = False
        for ch in (min(2, info["max_output_channels"]), 1):
            if ch < 1:
                continue
            try:
                self.channels = ch
                self.stream = sd.OutputStream(
                    device=self.device, channels=ch, samplerate=SAMPLERATE,
                    dtype=DTYPE, blocksize=BLOCK, latency="low",
                    extra_settings=extra_settings(self.device),
                    callback=self._callback,
                )
                self.stream.start()
                opened = True
                break
            except Exception as e:
                last = e
        if not opened:
            raise RuntimeError("Nao consegui abrir a saida {}:\n  {}{}".format(
                describe(self.device), last, dica_taxa()))
        threading.Thread(target=self._net_loop, daemon=True).start()

    def stop(self):
        self.running = False
        if self.stream:
            self.stream.stop()
            self.stream.close()


# -------------------------------------------------------------- monitor

def monitor(stats, receiver, label):
    t0 = time.time()
    last = dict(stats)
    while True:
        time.sleep(1.0)
        now = dict(stats)
        tx = now["tx"] - last["tx"]
        rx = now["rx"] - last["rx"]
        last = now

        bar_n = int(min(1.0, stats["level"]) * 20)
        bar = "#" * bar_n + "-" * (20 - bar_n)
        parts = ["{:5d}s".format(int(time.time() - t0))]

        if label == "send":
            parts.append("mic [{}]  enviados {}/s".format(bar, tx))
        else:
            depth = receiver.jb.depth() if receiver else 0
            parts.append("recebidos {}/s  buffer {:3d}ms".format(rx, depth * 10))
            if receiver:
                parts.append("falhas {}".format(receiver.jb.underruns))
        if stats["lost"]:
            parts.append("perdidos {}".format(stats["lost"]))
        if stats["rejected"]:
            parts.append("rejeitados {}".format(stats["rejected"]))

        print("  " + "   ".join(parts) + "        ", end="\r", flush=True)


def new_stats():
    return {"tx": 0, "rx": 0, "lost": 0, "rejected": 0, "level": 0.0}


def local_ips():
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    return ips or ["<ip-deste-pc>"]


# ------------------------------------------------------------------ modos


# ------------------------------------------------------- descoberta automatica

def broadcast_addrs():
    """Enderecos de broadcast plausiveis desta maquina."""
    addrs = ["255.255.255.255"]
    for ip in local_ips():
        if ip.count(".") == 3 and not ip.startswith("169.254."):
            b = ".".join(ip.split(".")[:3] + ["255"])
            if b not in addrs:
                addrs.append(b)
    return addrs


def anunciar(token, port, parar):
    """PC: avisa a rede que esta pronto, ate mandarem parar."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    pacote = BEACON + token + struct.pack("<I", port)
    while not parar.is_set():
        for alvo in broadcast_addrs():
            try:
                s.sendto(pacote, (alvo, DISCOVERY_PORT))
            except Exception:
                pass
        parar.wait(1.0)
    s.close()


def procurar_pc(token, timeout=None):
    """Notebook: escuta ate ouvir um PC. Devolve (ip, porta) ou None."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", DISCOVERY_PORT))
    except Exception as e:
        s.close()
        raise RuntimeError("Nao consegui escutar a porta de descoberta: %s" % e)
    s.settimeout(1.0)
    inicio = time.time()
    try:
        while True:
            try:
                dados, origem = s.recvfrom(64)
            except socket.timeout:
                if timeout and (time.time() - inicio) > timeout:
                    return None
                continue
            if len(dados) >= 12 and dados[:4] == BEACON and dados[4:8] == token:
                return (origem[0], struct.unpack("<I", dados[8:12])[0])
    finally:
        s.close()


def cmd_send(args):
    token = token_of(args.secret)
    mic = find_device(args.mic, "input")

    if args.to is None:
        print("\nProcurando o PC na rede...", flush=True)
        achado = procurar_pc(token)
        if achado is None:
            print("Nao achei nenhum PC anunciando.")
            sys.exit(1)
        args.to, args.port = achado
        print("  achei: " + args.to, flush=True)

    peer = [(args.to, args.port)]

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.5)
    sock.bind(("0.0.0.0", 0))

    stats = new_stats()
    print("\nAudioLink  ENVIANDO microfone -> {}:{}".format(args.to, args.port))
    print("  microfone: " + describe(mic))

    sender = Sender(sock, mic, peer, token, stats)
    sender.start()

    receiver = None
    if args.duplex:
        spk = find_device(args.speaker, "output")
        print("  retorno:   " + describe(spk))
        receiver = Receiver(sock, spk, token, stats, args.jitter)
        receiver.start()

    print("\n  Ctrl+C para parar.\n")
    try:
        monitor(stats, receiver, "send")
    except KeyboardInterrupt:
        print("\n\n  parando...")
    finally:
        sender.stop()
        if receiver:
            receiver.stop()
        sock.close()


def cmd_recv(args):
    token = token_of(args.secret)

    if args.out is None:
        try:
            out = find_device("CABLE Input", "output")
        except RuntimeError:
            # Sem VB-Cable: usa a saida que a Mixagem estereo escuta.
            try:
                out = find_device("Altofalantes", "output")
                print("\nVB-Cable nao existe aqui. Usando o plano B:")
                print("  saida -> " + describe(out))
                print("  No Teams/MicroSIP escolha 'Mixagem estereo' como MICROFONE.")
            except RuntimeError:
                out = None
        if out is None:
            print("\nVB-Cable nao encontrado nesta maquina.\n")
            print("Sem admin nao da pra instalar driver, mas existe o plano B:")
            print("a 'Mixagem estereo' (Stereo Mix), que a maioria das placas")
            print("Realtek ja tem. Ela funciona como microfone capturando o que")
            print("estiver tocando no PC.\n")
            print("  1. Habilite a Mixagem estereo:")
            print("     Som -> Mais configuracoes de som -> aba Gravacao")
            print("     botao direito -> Mostrar dispositivos desabilitados -> Habilitar")
            print("  2. Rode o AudioLink apontando para a saida que ela escuta:")
            print("     python audiolink.py recv --out <numero da saida>")
            print("  3. No MicroSIP / Teams, escolha 'Mixagem estereo' como microfone\n")
            print("Para descobrir o numero certo e evitar eco, rode primeiro:")
            print("   python audiolink.py checar\n")
            sys.exit(1)
    else:
        out = find_device(args.out, "output")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.5)
    sock.bind(("0.0.0.0", args.port))

    # Anuncia na rede para o notebook achar sozinho, sem digitar IP.
    parar_anuncio = threading.Event()
    threading.Thread(target=anunciar, args=(token, args.port, parar_anuncio),
                     daemon=True).start()

    stats = new_stats()
    peer = [None]

    print("\nAudioLink  RECEBENDO microfone na porta UDP {}".format(args.port))
    print("  saida: " + describe(out))
    print("\n  No notebook, rode um destes:")
    for ip in local_ips():
        print("     python audiolink.py send --to " + ip)

    receiver = Receiver(sock, out, token, stats, args.jitter, learn_peer=peer)
    receiver.start()

    sender = None
    if args.duplex:
        cap = find_device(args.mic, "input")
        print("  retorno: " + describe(cap))
        sender = Sender(sock, cap, peer, token, stats)
        sender.start()

    print("\n  Ctrl+C para parar.\n")
    try:
        monitor(stats, receiver, "recv")
    except KeyboardInterrupt:
        print("\n\n  parando...")
    finally:
        receiver.stop()
        if sender:
            sender.stop()
        sock.close()


# ------------------------------------------------- descoberta do stereo mix

NOMES_MIX = ["Mixagem est", "Stereo Mix", "Mixagem Est", "What U Hear", "Mixage"]


def achar_mix():
    for nome in NOMES_MIX:
        try:
            return find_device(nome, "input")
        except RuntimeError:
            continue
    return None


def canais_de_entrada(in_dev, fs=48000, espera=0.35):
    """Descobre com quantos canais este device entrega audio de verdade.

    Stereo Mix e outros devices de loopback recusam mono na pratica: o
    PortAudio abre o stream sem erro nenhum, mas o callback nunca dispara
    e a captura volta vazia - o que faria toda saida parecer "nao escuta".
    Como nao da para saber isso pela ficha do device, testa-se na marra.
    """
    nativo = int(sd.query_devices(in_dev)["max_input_channels"])
    for ch in dict.fromkeys([c for c in (min(2, nativo), nativo, 1) if c >= 1]):
        chegou = []
        try:
            with sd.InputStream(device=in_dev, channels=ch, samplerate=fs,
                                dtype="int16", extra_settings=extra_settings(in_dev),
                                callback=lambda d, f, t, s: chegou.append(1)):
                time.sleep(espera)
        except Exception:
            continue
        if chegou:
            return ch
    return None


def medir(out_dev, in_dev, ch_in, dur=1.2):
    """Toca um tom numa saida e mede quanto dele a Mixagem estereo capta."""
    fs = 48000
    n = int(fs * dur)
    t = np.arange(n) / fs
    tom = (np.sin(2 * np.pi * 997 * t) * 0.3 * 32767).astype(np.int16)

    gravado = []
    pos = [0]
    fim = threading.Event()

    def out_cb(outdata, frames, ti, st):
        i = pos[0]
        pedaco = tom[i:i + frames]
        outdata.fill(0)
        if len(pedaco) == 0:
            raise sd.CallbackStop
        for c in range(outdata.shape[1]):
            outdata[:len(pedaco), c] = pedaco
        pos[0] += frames

    def in_cb(indata, frames, ti, st):
        gravado.append(indata.copy())

    info_out = sd.query_devices(out_dev)
    ch_out = min(2, info_out["max_output_channels"]) or 1

    with sd.InputStream(device=in_dev, channels=ch_in, samplerate=fs, dtype="int16",
                        extra_settings=extra_settings(in_dev), callback=in_cb):
        time.sleep(0.25)                      # ruido de fundo antes do tom
        base = np.concatenate(gravado) if gravado else np.zeros(1, dtype=np.int16)
        piso = float(np.abs(base).mean()) + 1.0
        gravado.clear()
        with sd.OutputStream(device=out_dev, channels=ch_out, samplerate=fs,
                             dtype="int16", extra_settings=extra_settings(out_dev),
                             callback=out_cb, finished_callback=fim.set):
            fim.wait(timeout=dur + 1.5)
        time.sleep(0.15)

    if not gravado:
        return 0.0
    sinal = np.concatenate(gravado).astype(np.float32)
    return float(np.abs(sinal).mean()) / piso   # quantas vezes acima do silencio


def cmd_checar(args):
    mix = achar_mix()
    if mix is None:
        print("\nNao achei a 'Mixagem estereo' entre os microfones.\n")
        print("Habilite assim (nao precisa de admin):")
        print("  1. Botao direito no icone de som -> Configuracoes de som")
        print("  2. Role ate o fim -> 'Mais configuracoes de som'")
        print("  3. Aba 'Gravacao' -> botao direito numa area vazia")
        print("  4. Marque 'Mostrar dispositivos desabilitados'")
        print("  5. Botao direito em 'Mixagem estereo' -> Habilitar\n")
        print("Se ela nao existir mesmo neste PC, o jeito e o VB-Cable")
        print("(precisa do TI). Veja o LEIA-ME.\n")
        sys.exit(1)

    print("\nMicrofone virtual encontrado: " + describe(mix))

    ch_in = canais_de_entrada(mix)
    if ch_in is None:
        print("\nEle aparece na lista, mas nao entregou audio nenhum.")
        print("Verifique em Som -> Gravacao -> Mixagem estereo:")
        print("  - esta Habilitado?")
        print("  - em Propriedades -> Niveis, o volume esta acima de zero?\n")
        sys.exit(1)
    print("capturando em {} canal(is)".format(ch_in))

    print("\nVou tocar um tom curto em cada saida e medir qual delas")
    print("a Mixagem estereo escuta. Voce vai ouvir uns bipes.\n")

    wasapi = wasapi_index()
    saidas = [i for i, d in enumerate(sd.query_devices())
              if d["max_output_channels"] > 0 and d["hostapi"] == wasapi]

    resultados = []
    for s in saidas:
        nome = sd.query_devices(s)["name"]
        print("  testando {:40.40s} ".format(nome), end="", flush=True)
        try:
            r = medir(s, mix, ch_in)
        except Exception as e:
            print("nao deu (" + str(e)[:30] + ")")
            continue
        resultados.append((r, s, nome))
        print("{}  ({:.0f}x)".format("ESCUTA" if r > 4 else "nao escuta", r))

    ouvidas = [x for x in resultados if x[0] > 4]
    mudas = [x for x in resultados if x[0] <= 4]

    print("\n" + "=" * 58)
    if not ouvidas:
        print("A Mixagem estereo nao captou nenhuma saida.")
        print("Verifique se ela esta habilitada e com volume acima de zero")
        print("em Som -> Gravacao -> Mixagem estereo -> Propriedades -> Niveis.")
        sys.exit(1)

    melhor = max(ouvidas)
    print("CONFIGURACAO PARA ESTE PC:\n")
    print("  1. Rode o AudioLink assim (sua voz vai por aqui):")
    print("       python audiolink.py recv --out {}".format(melhor[1]))
    print("       -> {}".format(melhor[2]))
    print("\n  2. No MicroSIP e no Teams, escolha como MICROFONE:")
    print("       {}".format(sd.query_devices(mix)["name"]))

    if mudas:
        alt = mudas[0]
        print("\n  3. IMPORTANTE - para a outra pessoa nao se ouvir,")
        print("     mande o MicroSIP e o Teams TOCAREM em outra saida:")
        print("       {}".format(alt[2]))
        print("     Ajuste em: Configuracoes -> Sistema -> Som -> Mixer de volume")
    else:
        print("\n  3. PROBLEMA: todas as saidas caem na Mixagem estereo.")
        print("     Do jeito que esta, a outra pessoa vai se ouvir com atraso.")
        print("\n     Antes de desistir, procure uma saida INDEPENDENTE do")
        print("     Realtek e ligue ela. Costuma funcionar:")
        print("       - HDMI ou DisplayPort do monitor (se tiver alto-falante)")
        print("       - qualquer adaptador de som USB")
        print("       - fone ou caixa Bluetooth pareado")
        print("     Depois rode este 'checar' de novo: se a saida nova aparecer")
        print("     como 'nao escuta', o problema esta resolvido.")
        print("\n     Se nenhuma servir, so o VB-Cable resolve. Veja o LEIA-ME.")
    print("=" * 58 + "\n")


# -------------------------------------------------------------------- cli

def main():
    p = argparse.ArgumentParser(
        description="Leva o microfone do notebook para o PC remoto em tempo real.")
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="porta UDP (padrao 50505)")
    common.add_argument("--secret", default="audiolink",
                        help="segredo compartilhado, igual nos dois lados")
    common.add_argument("--jitter", type=int, default=40,
                        help="buffer de rede em ms (padrao 40)")
    common.add_argument("--hz", type=int, default=48000,
                        choices=[16000, 24000, 48000],
                        help="taxa de amostragem; 16000 gasta 1/3 da banda. Igual nos dois lados")
    common.add_argument("--duplex", action="store_true",
                        help="tambem trazer o audio do outro lado de volta")

    s = sub.add_parser("send", parents=[common], help="NOTEBOOK: envia o microfone")
    s.add_argument("--to", help="IP do PC (se omitir, acha sozinho na rede)")
    s.add_argument("--mic", help="indice ou trecho do nome do microfone")
    s.add_argument("--speaker", help="saida para o retorno, se usar --duplex")

    r = sub.add_parser("recv", parents=[common],
                       help="PC: recebe e injeta no microfone virtual")
    r.add_argument("--out", help="saida (padrao: CABLE Input do VB-Cable)")
    r.add_argument("--mic", help="entrada para o retorno, se usar --duplex")

    sub.add_parser("list", help="lista os dispositivos de audio desta maquina")
    sub.add_parser("checar", parents=[common],
                   help="PC sem VB-Cable: descobre a configuracao do Stereo Mix")

    args = p.parse_args()

    if getattr(args, "hz", None):
        global SAMPLERATE, BLOCK
        SAMPLERATE = args.hz
        BLOCK = args.hz // 100      # sempre 10 ms por pacote

    if args.cmd == "list":
        cmd_list()
    elif args.cmd == "checar":
        cmd_checar(args)
    elif args.cmd == "send":
        cmd_send(args)
    else:
        cmd_recv(args)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        print("\nERRO: {}\n".format(e))
        sys.exit(1)
