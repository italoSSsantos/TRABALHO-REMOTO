#!/usr/bin/env python3
"""
Painel visual do audio - janela que mostra, ao vivo, se o microfone do
notebook chegou no PC pela sessao RDP.

Rode DENTRO da sessao RDP, no PC:
    python painel.py
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import font as tkfont

import numpy as np
import sounddevice as sd

MARCAS_REMOTO = ("remote audio", "audio remoto", "\xe1udio remoto", "rdp",
                 "redirecionamento de audio", "redirecionamento de \xe1udio")

FUNDO   = "#15171c"
CARTAO  = "#1e2129"
BORDA   = "#2c303b"
TEXTO   = "#e8eaf0"
FRACO   = "#848b9e"
VERDE   = "#3ddc84"
AMARELO = "#ffc857"
VERMELHO = "#ff5c5c"
TRILHO  = "#2a2e38"


def e_remoto(nome):
    n = (nome or "").lower()
    return any(m in n for m in MARCAS_REMOTO)


def sessao():
    nome = os.environ.get("SESSIONNAME", "?")
    return nome, nome.upper().startswith("RDP")


def padroes():
    """Dispositivos padrao do Windows. Reinicia o PortAudio para ver trocas."""
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


class Audio(threading.Thread):
    """Mede o nivel do microfone padrao numa thread propria."""

    daemon = True

    def __init__(self):
        super().__init__()
        self.saida = queue.Queue()
        self.pico = 0.0
        self.parar = threading.Event()

    def run(self):
        stream = None
        dev_atual = object()
        while not self.parar.is_set():
            ent, sai = padroes()
            if ent[0] != dev_atual:
                if stream:
                    try:
                        stream.stop(); stream.close()
                    except Exception:
                        pass
                    stream = None
                dev_atual = ent[0]
                if ent[0] is not None:
                    stream = self._abrir(ent[0])
            self.saida.put((ent, sai, stream is not None))
            self.parar.wait(3.0)
        if stream:
            try:
                stream.stop(); stream.close()
            except Exception:
                pass

    def _abrir(self, dev):
        canais = int(sd.query_devices(dev)["max_input_channels"])
        for ch in dict.fromkeys([c for c in (1, min(2, canais), canais) if c >= 1]):
            try:
                s = sd.InputStream(device=dev, channels=ch, samplerate=48000,
                                   dtype="int16", blocksize=480, callback=self._cb)
                s.start()
                return s
            except Exception:
                continue
        return None

    def _cb(self, indata, frames, t, s):
        v = float(np.abs(indata).max()) / 32768.0
        self.pico = max(self.pico * 0.6, v)


class Painel:
    def __init__(self, raiz):
        self.raiz = raiz
        raiz.title("Audio do PC")
        raiz.configure(bg=FUNDO)
        raiz.geometry("560x520")
        raiz.minsize(480, 480)

        self.f_titulo = tkfont.Font(family="Segoe UI", size=17, weight="bold")
        self.f_rotulo = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self.f_valor  = tkfont.Font(family="Segoe UI", size=12)
        self.f_nota   = tkfont.Font(family="Segoe UI", size=9)
        self.f_status = tkfont.Font(family="Segoe UI", size=12, weight="bold")

        tk.Label(raiz, text="Audio do PC", bg=FUNDO, fg=TEXTO,
                 font=self.f_titulo).pack(anchor="w", padx=24, pady=(22, 0))
        self.lb_maquina = tk.Label(raiz, text=os.environ.get("COMPUTERNAME", ""),
                                   bg=FUNDO, fg=FRACO, font=self.f_nota)
        self.lb_maquina.pack(anchor="w", padx=24, pady=(2, 16))

        self.c_sessao, self.v_sessao, self.n_sessao = self._cartao("SESSAO")
        self.c_mic, self.v_mic, self.n_mic = self._cartao("MICROFONE", barra=True)
        self.c_saida, self.v_saida, self.n_saida = self._cartao("SAIDA")

        self.lb_status = tk.Label(raiz, text="lendo...", bg=FUNDO, fg=FRACO,
                                  font=self.f_status, wraplength=500,
                                  justify="left", anchor="w")
        self.lb_status.pack(fill="x", padx=24, pady=(6, 20))

        self.audio = Audio()
        self.audio.start()
        self.ent = self.sai = (None, "lendo...")
        raiz.protocol("WM_DELETE_WINDOW", self.fechar)
        self.tick()

    def _cartao(self, titulo, barra=False):
        c = tk.Frame(self.raiz, bg=CARTAO, highlightbackground=BORDA,
                     highlightthickness=1)
        c.pack(fill="x", padx=24, pady=5)
        tk.Label(c, text=titulo, bg=CARTAO, fg=FRACO,
                 font=self.f_rotulo).pack(anchor="w", padx=16, pady=(12, 2))
        valor = tk.Label(c, text="-", bg=CARTAO, fg=TEXTO, font=self.f_valor,
                         anchor="w", justify="left", wraplength=470)
        valor.pack(anchor="w", padx=16)
        nota = tk.Label(c, text="", bg=CARTAO, fg=FRACO, font=self.f_nota,
                        anchor="w", justify="left", wraplength=470)
        nota.pack(anchor="w", padx=16, pady=(1, 0))
        if barra:
            self.cv = tk.Canvas(c, height=22, bg=TRILHO, highlightthickness=0)
            self.cv.pack(fill="x", padx=16, pady=(10, 0))
            self.lb_pct = tk.Label(c, text="0%  silencio", bg=CARTAO, fg=FRACO,
                                   font=self.f_nota, anchor="w")
            self.lb_pct.pack(anchor="w", padx=16, pady=(4, 0))
        tk.Frame(c, bg=CARTAO, height=12).pack()
        return c, valor, nota

    def tick(self):
        while True:
            try:
                self.ent, self.sai, _ = self.audio.saida.get_nowait()
            except queue.Empty:
                break

        nome_sessao, remoto = sessao()
        self.v_sessao.config(text=nome_sessao,
                             fg=VERDE if remoto else AMARELO)
        self.n_sessao.config(text="voce conectado por RDP" if remoto
                             else "sessao local - sem RDP nao existe microfone redirecionado")

        mic_nome = self.ent[1]
        mic_remoto = e_remoto(mic_nome)
        self.v_mic.config(text=mic_nome)
        if mic_remoto:
            self.n_mic.config(text="vem do headset do notebook", fg=VERDE)
        elif remoto:
            self.n_mic.config(text="dispositivo local do PC - nao e o seu headset",
                              fg=VERMELHO)
        else:
            self.n_mic.config(text="dispositivo local", fg=FRACO)

        pico = self.audio.pico
        self.audio.pico *= 0.85
        larg = max(1, self.cv.winfo_width())
        self.cv.delete("all")
        n = int(min(1.0, pico) * larg)
        cor = VERMELHO if pico > 0.75 else (VERDE if pico > 0.02 else TRILHO)
        if n > 0:
            self.cv.create_rectangle(0, 0, n, 22, fill=cor, width=0)
        pct = int(min(1.0, pico) * 100)
        falando = pico > 0.02
        self.lb_pct.config(text="{}%  {}".format(pct, "CAPTANDO" if falando else "silencio"),
                           fg=VERDE if falando else FRACO)

        sai_nome = self.sai[1]
        self.v_saida.config(text=sai_nome)
        if e_remoto(sai_nome):
            self.n_saida.config(text="vai para o headset do notebook", fg=VERDE)
        elif remoto:
            self.n_saida.config(text="toca no PC - voce nao vai ouvir", fg=AMARELO)
        else:
            self.n_saida.config(text="dispositivo local", fg=FRACO)

        if not remoto:
            self.lb_status.config(text="Conecte pelo RDP para o microfone aparecer.",
                                  fg=FRACO)
        elif mic_remoto and e_remoto(sai_nome):
            self.lb_status.config(
                text="TUDO CERTO - MicroSIP e Teams em 'Padrao' usam seu headset.",
                fg=VERDE)
        elif mic_remoto:
            self.lb_status.config(
                text="Microfone OK, mas o som do PC nao esta vindo para voce.",
                fg=AMARELO)
        else:
            self.lb_status.config(
                text="O padrao NAO e o audio remoto. Em Som -> Entrada, "
                     "escolha 'Redirecionamento de Audio Remoto'.",
                fg=VERMELHO)

        self.raiz.after(60, self.tick)

    def fechar(self):
        self.audio.parar.set()
        self.raiz.destroy()


if __name__ == "__main__":
    raiz = tk.Tk()
    Painel(raiz)
    raiz.mainloop()
