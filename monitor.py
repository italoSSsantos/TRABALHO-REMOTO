#!/usr/bin/env python3
"""
Painel em tempo real do audio do PC.

Mostra se o microfone do notebook chegou pela sessao RDP, qual dispositivo
o MicroSIP e o Teams vao pegar, e o nivel do que esta entrando agora.

Rode DENTRO da sessao RDP, no PC:
    python monitor.py
"""

import ctypes
import os
import sys
import time

import numpy as np
import sounddevice as sd

# nomes que o Windows da ao dispositivo criado pelo proprio RDP
MARCAS_REMOTO = ("remote audio", "audio remoto", "remoto", "rdp",
                 "redirecionamento de audio", "redirecionamento de \xe1udio")

ESC = "\x1b["
VERDE, AMARELO, VERMELHO, CINZA, NEGRITO, ZERA = (
    ESC + "32m", ESC + "33m", ESC + "31m", ESC + "90m", ESC + "1m", ESC + "0m")


def liga_cores():
    if os.name == "nt":
        try:                                   # habilita ANSI no console classico
            k = ctypes.windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)
        except Exception:
            pass


def sessao():
    """Console = alguem sentado no PC. RDP-Tcp#N = conectado remotamente."""
    nome = os.environ.get("SESSIONNAME", "?")
    if nome.upper().startswith("RDP"):
        return nome, True
    return nome, False


def e_remoto(nome_dispositivo):
    n = nome_dispositivo.lower()
    return any(m in n for m in MARCAS_REMOTO)


def padroes():
    """Le os dispositivos padrao, reiniciando o PortAudio para pegar trocas."""
    try:
        sd._terminate()
        sd._initialize()
    except Exception:
        pass

    def pega(kind):
        try:
            for api in sd.query_hostapis():
                if api["name"] == "Windows WASAPI":
                    i = api["default_" + kind + "_device"]
                    if i is not None and i >= 0:
                        return i, sd.query_devices(i)["name"]
            i = sd.default.device[0 if kind == "input" else 1]
            if i is not None and i >= 0:
                return i, sd.query_devices(i)["name"]
        except Exception:
            pass
        return None, "(nenhum)"

    return pega("input"), pega("output")


class Nivel:
    """Mede o nivel do microfone padrao, reabrindo se o dispositivo trocar."""

    def __init__(self):
        self.stream = None
        self.dev = None
        self.pico = 0.0
        self.erro = None

    def aponta(self, dev):
        if dev == self.dev and self.stream is not None:
            return
        self.fecha()
        self.dev = dev
        self.erro = None
        if dev is None:
            return
        canais = int(sd.query_devices(dev)["max_input_channels"])
        for ch in dict.fromkeys([c for c in (1, min(2, canais), canais) if c >= 1]):
            try:
                self.stream = sd.InputStream(
                    device=dev, channels=ch, samplerate=48000,
                    dtype="int16", blocksize=480, callback=self._cb)
                self.stream.start()
                return
            except Exception as e:
                self.erro = str(e)[:50]
        self.stream = None

    def _cb(self, indata, frames, t, s):
        v = float(np.abs(indata).max()) / 32768.0
        self.pico = max(self.pico * 0.7, v)     # decai suave, nao pisca

    def fecha(self):
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
        self.stream = None


def barra(v, largura=28):
    n = int(min(1.0, v) * largura)
    if v > 0.75:
        cor = VERMELHO
    elif v > 0.02:
        cor = VERDE
    else:
        cor = CINZA
    return cor + "#" * n + CINZA + "-" * (largura - n) + ZERA


def desenha(nome_sessao, remoto, ent, sai, nivel, segundos):
    linhas = []
    add = linhas.append

    add("")
    add("  " + NEGRITO + "AUDIO DO PC  -  " + os.environ.get("COMPUTERNAME", "?") + ZERA)
    add("  " + CINZA + "-" * 58 + ZERA)
    add("")

    if remoto:
        add("  SESSAO     " + VERDE + nome_sessao + ZERA + "  (voce conectado por RDP)")
    else:
        add("  SESSAO     " + AMARELO + nome_sessao + ZERA + "  (sessao local do PC)")
        add("             " + CINZA + "sem RDP nao existe microfone redirecionado" + ZERA)
    add("")

    # ---- microfone
    ent_idx, ent_nome = ent
    veio_do_note = e_remoto(ent_nome)
    if veio_do_note:
        marca = VERDE + "[headset do notebook]" + ZERA
    elif remoto:
        marca = VERMELHO + "[dispositivo local do PC]" + ZERA
    else:
        marca = CINZA + "[local]" + ZERA

    add("  " + NEGRITO + "MICROFONE" + ZERA + "  " + ent_nome[:44])
    add("             " + marca)
    if nivel.erro:
        add("             " + VERMELHO + "nao consegui abrir: " + nivel.erro + ZERA)
    else:
        pct = int(min(1.0, nivel.pico) * 100)
        estado = (VERDE + "CAPTANDO" + ZERA) if nivel.pico > 0.02 else (CINZA + "silencio" + ZERA)
        add("             " + barra(nivel.pico) + "  {:3d}%  {}".format(pct, estado))
    add("")

    # ---- saida
    sai_idx, sai_nome = sai
    add("  " + NEGRITO + "SAIDA    " + ZERA + "  " + sai_nome[:44])
    if e_remoto(sai_nome):
        add("             " + VERDE + "[vai para o headset do notebook]" + ZERA)
    elif remoto:
        add("             " + AMARELO + "[toca no PC - voce nao vai ouvir]" + ZERA)
    else:
        add("             " + CINZA + "[local]" + ZERA)
    add("")
    add("  " + CINZA + "-" * 58 + ZERA)

    # ---- veredito
    if not remoto:
        add("  " + CINZA + "Conecte pelo RDP para o microfone aparecer." + ZERA)
    elif veio_do_note and e_remoto(sai_nome):
        add("  " + VERDE + "TUDO CERTO." + ZERA +
            " MicroSIP e Teams em 'Padrao' usam seu headset.")
    elif veio_do_note:
        add("  " + AMARELO + "Microfone OK, mas o som do PC nao vem para voce." + ZERA)
    else:
        add("  " + VERMELHO + "O padrao NAO e o audio remoto." + ZERA)
        add("  " + CINZA + "Som -> Entrada: escolha 'Redirecionamento de Audio Remoto'." + ZERA)

    add("")
    add("  " + CINZA + "{}s   atualiza sozinho   Ctrl+C para sair".format(segundos) + ZERA)
    add("")

    sys.stdout.write(ESC + "H" + ESC + "J" + "\n".join(linhas) + "\n")
    sys.stdout.flush()


def main():
    liga_cores()
    sys.stdout.write(ESC + "2J")
    nivel = Nivel()
    t0 = time.time()
    ent = sai = (None, "(lendo...)")
    ultima_leitura = 0.0

    try:
        while True:
            agora = time.time()
            # reler os padroes exige reiniciar o PortAudio, entao espaca um pouco
            if agora - ultima_leitura > 3.0:
                nivel.fecha()
                ent, sai = padroes()
                nivel.aponta(ent[0])
                ultima_leitura = agora
            desenha(sessao()[0], sessao()[1], ent, sai, nivel, int(agora - t0))
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        nivel.fecha()
        print()


if __name__ == "__main__":
    main()
