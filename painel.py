#!/usr/bin/env python3
"""
Painel de controle do audio remoto.

Mostra ao vivo se o microfone chegou e tem os botoes para ligar tudo:
conectar por RDP (em casa) ou subir o AudioLink (fora de casa).

    python painel.py
"""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont

import numpy as np
import sounddevice as sd

AQUI = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_RDP = os.path.join(AQUI, "PC DO TRABALHO (com microfone).rdp")
IP_PADRAO = "192.168.0.244"

MARCAS_REMOTO = ("remote audio", "audio remoto", "\xe1udio remoto", "rdp",
                 "redirecionamento de audio", "redirecionamento de \xe1udio")

FUNDO, CARTAO, BORDA = "#15171c", "#1e2129", "#2c303b"
TEXTO, FRACO, TRILHO = "#e8eaf0", "#848b9e", "#2a2e38"
VERDE, AMARELO, VERMELHO, AZUL = "#3ddc84", "#ffc857", "#ff5c5c", "#4c8dff"


def e_remoto(nome):
    n = (nome or "").lower()
    return any(m in n for m in MARCAS_REMOTO)


def sessao():
    nome = os.environ.get("SESSIONNAME", "?")
    return nome, nome.upper().startswith("RDP")


def padroes():
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
    """Le o nivel do microfone padrao sem travar a janela."""

    daemon = True

    def __init__(self):
        super().__init__()
        self.saida = queue.Queue()
        self.pico = 0.0
        self.parar = threading.Event()

    def run(self):
        stream, dev_atual = None, object()
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
            self.saida.put((ent, sai))
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
        self.pico = max(self.pico * 0.6, float(np.abs(indata).max()) / 32768.0)


class Rolavel(tk.Frame):
    """Area com rolagem: a janela pode ficar menor que o conteudo."""

    def __init__(self, pai, bg):
        super().__init__(pai, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.barra = tk.Scrollbar(self, orient="vertical",
                                  command=self.canvas.yview, width=11)
        self.canvas.configure(yscrollcommand=self._scroll_set)
        # grid, e nao pack: grid_remove() esconde a barra sem perder o lugar dela
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.barra.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.interno = tk.Frame(self.canvas, bg=bg)
        self.janela = self.canvas.create_window((0, 0), window=self.interno,
                                                anchor="nw")
        self.interno.bind("<Configure>", self._conteudo_mudou)
        self.canvas.bind("<Configure>", self._canvas_mudou)
        self.canvas.bind_all("<MouseWheel>", self._roda)

    def _scroll_set(self, primeiro, ultimo):
        # so mostra a barra quando ha o que rolar
        if float(primeiro) <= 0.0 and float(ultimo) >= 1.0:
            self.barra.grid_remove()
        else:
            self.barra.grid()
        self.barra.set(primeiro, ultimo)

    def _conteudo_mudou(self, _):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _canvas_mudou(self, e):
        self.canvas.itemconfigure(self.janela, width=e.width)
        # encolher so o canvas nao mexe no conteudo, entao o scrollregion
        # precisa ser refeito aqui - senao a barra nunca aparece
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _roda(self, e):
        if self.canvas.winfo_exists():
            self.canvas.yview_scroll(int(-e.delta / 120), "units")


class Painel:
    def __init__(self, raiz):
        self.raiz = raiz
        raiz.title("Audio remoto")
        raiz.configure(bg=FUNDO)
        raiz.geometry("400x520")
        raiz.minsize(300, 200)          # da para encolher bem; o scroll cobre

        self.f_h1   = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        self.f_rot  = tkfont.Font(family="Segoe UI", size=8, weight="bold")
        self.f_val  = tkfont.Font(family="Segoe UI", size=10)
        self.f_nota = tkfont.Font(family="Segoe UI", size=8)
        self.f_bt   = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.f_st   = tkfont.Font(family="Segoe UI", size=9, weight="bold")

        self.proc = None
        self.ent = self.sai = (None, "lendo...")
        self.ultima_linha = ""

        rol = Rolavel(raiz, FUNDO)
        rol.pack(fill="both", expand=True)
        self.area = rol.interno

        topo = tk.Frame(self.area, bg=FUNDO)
        topo.pack(fill="x", padx=14, pady=(12, 8))
        tk.Label(topo, text="Audio remoto", bg=FUNDO, fg=TEXTO,
                 font=self.f_h1).pack(side="left")
        tk.Label(topo, text=os.environ.get("COMPUTERNAME", ""), bg=FUNDO,
                 fg=FRACO, font=self.f_nota).pack(side="right", pady=(4, 0))

        # ------------------------------------------------ acao principal
        self.bt_rdp = tk.Button(self.area, text="CONECTAR AO PC POR RDP",
                                command=self.abrir_rdp, font=self.f_bt,
                                bg=AZUL, fg="white", activebackground="#3b78e0",
                                activeforeground="white", relief="flat",
                                cursor="hand2", pady=9)
        self.bt_rdp.pack(fill="x", padx=14)
        tk.Label(self.area, text="leva microfone e camera junto", bg=FUNDO,
                 fg=FRACO, font=self.f_nota).pack(anchor="w", padx=14, pady=(3, 8))

        # ------------------------------------------------------ ao vivo
        self.v_ses, self.n_ses = self._cartao("SESSAO")
        self.v_mic, self.n_mic = self._cartao("MICROFONE", barra=True)
        self.v_sai, self.n_sai = self._cartao("SAIDA")

        self.lb_status = tk.Label(self.area, text="lendo...", bg=FUNDO, fg=FRACO,
                                  font=self.f_st, wraplength=340,
                                  justify="left", anchor="w")
        self.lb_status.pack(fill="x", padx=14, pady=(6, 10))

        # -------------------------- fora de casa: recolhido por ser plano B
        self.aberto = tk.BooleanVar(value=False)
        self.bt_exp = tk.Button(self.area, text="▸  Fora de casa (AudioLink)",
                                command=self.alterna_secao, font=self.f_nota,
                                bg=FUNDO, fg=FRACO, activebackground=FUNDO,
                                activeforeground=TEXTO, relief="flat",
                                cursor="hand2", anchor="w", bd=0, pady=4)
        self.bt_exp.pack(fill="x", padx=12)

        self.secao = tk.Frame(self.area, bg=CARTAO, highlightbackground=BORDA,
                              highlightthickness=1)
        linha = tk.Frame(self.secao, bg=CARTAO)
        linha.pack(fill="x", padx=11, pady=(9, 5))
        tk.Label(linha, text="IP do PC", bg=CARTAO, fg=FRACO,
                 font=self.f_nota).pack(side="left")
        self.ip = tk.Entry(linha, bg=TRILHO, fg=TEXTO, insertbackground=TEXTO,
                           relief="flat", font=self.f_val, width=15)
        self.ip.insert(0, IP_PADRAO)
        self.ip.pack(side="left", padx=7, ipady=2)

        self.modo = tk.StringVar(value="recv" if sessao()[1] else "send")
        for val, txt in (("send", "Enviar microfone (notebook)"),
                         ("recv", "Receber microfone (PC)")):
            tk.Radiobutton(self.secao, text=txt, variable=self.modo, value=val,
                           bg=CARTAO, fg=TEXTO, selectcolor=TRILHO,
                           activebackground=CARTAO, activeforeground=TEXTO,
                           font=self.f_nota, anchor="w",
                           highlightthickness=0, bd=0).pack(fill="x", padx=9)

        self.bt_iniciar = tk.Button(self.secao, text="INICIAR", command=self.alternar,
                                    font=self.f_bt, bg=VERDE, fg="#11301f",
                                    activebackground="#35c476", relief="flat",
                                    cursor="hand2", pady=7)
        self.bt_iniciar.pack(fill="x", padx=11, pady=(7, 3))
        self.lb_proc = tk.Label(self.secao, text="parado", bg=CARTAO, fg=FRACO,
                                font=self.f_nota, anchor="w", wraplength=330,
                                justify="left")
        self.lb_proc.pack(anchor="w", padx=11, pady=(0, 9))

        self.audio = Audio()
        self.audio.start()
        raiz.protocol("WM_DELETE_WINDOW", self.fechar)
        self.tick()

    # ------------------------------------------------------------ layout
    def _cartao(self, titulo, barra=False):
        c = tk.Frame(self.area, bg=CARTAO, highlightbackground=BORDA,
                     highlightthickness=1)
        c.pack(fill="x", padx=14, pady=3)
        tk.Label(c, text=titulo, bg=CARTAO, fg=FRACO,
                 font=self.f_rot).pack(anchor="w", padx=11, pady=(7, 1))
        valor = tk.Label(c, text="-", bg=CARTAO, fg=TEXTO, font=self.f_val,
                         anchor="w", justify="left", wraplength=320)
        valor.pack(anchor="w", padx=11)
        nota = tk.Label(c, text="", bg=CARTAO, fg=FRACO, font=self.f_nota,
                        anchor="w", justify="left", wraplength=320)
        nota.pack(anchor="w", padx=11)
        if barra:
            self.cv = tk.Canvas(c, height=16, bg=TRILHO, highlightthickness=0)
            self.cv.pack(fill="x", padx=11, pady=(6, 0))
            self.lb_pct = tk.Label(c, text="0%", bg=CARTAO, fg=FRACO,
                                   font=self.f_nota, anchor="w")
            self.lb_pct.pack(anchor="w", padx=11)
        tk.Frame(c, bg=CARTAO, height=7).pack()
        return valor, nota

    def alterna_secao(self):
        if self.aberto.get():
            self.secao.pack_forget()
            self.bt_exp.config(text="▸  Fora de casa (AudioLink)")
            self.aberto.set(False)
        else:
            self.secao.pack(fill="x", padx=14, pady=(0, 12))
            self.bt_exp.config(text="▾  Fora de casa (AudioLink)")
            self.aberto.set(True)

    # ------------------------------------------------------------ acoes
    def abrir_rdp(self):
        if not os.path.exists(ARQUIVO_RDP):
            self.lb_status.config(text="Nao achei o arquivo .rdp nesta pasta.",
                                  fg=VERMELHO)
            return
        try:
            os.startfile(ARQUIVO_RDP)
            self.lb_status.config(text="Abrindo a conexao RDP...", fg=AZUL)
        except Exception as e:
            self.lb_status.config(text="Nao consegui abrir: " + str(e)[:60],
                                  fg=VERMELHO)

    def alternar(self):
        if self.proc and self.proc.poll() is None:
            self.parar_proc()
        else:
            self.iniciar_proc()

    def iniciar_proc(self):
        modo = self.modo.get()
        cmd = [sys.executable, os.path.join(AQUI, "audiolink.py"), modo]
        if modo == "send":
            destino = self.ip.get().strip()
            if not destino:
                self.lb_proc.config(text="preencha o IP do PC", fg=VERMELHO)
                return
            cmd += ["--to", destino]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=AQUI, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, errors="replace", creationflags=flags)
        except Exception as e:
            self.lb_proc.config(text="nao iniciou: " + str(e)[:50], fg=VERMELHO)
            return
        threading.Thread(target=self._ler_saida, daemon=True).start()
        self.bt_iniciar.config(text="PARAR", bg=VERMELHO, fg="white",
                               activebackground="#e04b4b")
        self.lb_proc.config(text="iniciando...", fg=VERDE)

    def _ler_saida(self):
        try:
            for linha in self.proc.stdout:
                linha = linha.replace("\r", "").strip()
                if linha:
                    self.ultima_linha = linha[:60]
        except Exception:
            pass

    def parar_proc(self):
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.proc = None
        self.bt_iniciar.config(text="INICIAR", bg=VERDE, fg="#11301f",
                               activebackground="#35c476")
        self.lb_proc.config(text="parado", fg=FRACO)

    # ------------------------------------------------------------ ciclo
    def tick(self):
        while True:
            try:
                self.ent, self.sai = self.audio.saida.get_nowait()
            except queue.Empty:
                break

        nome_sessao, remoto = sessao()
        self.v_ses.config(text=nome_sessao, fg=VERDE if remoto else AMARELO)
        self.n_ses.config(text="conectado por RDP" if remoto
                          else "sessao local - sem microfone redirecionado")

        mic_nome = self.ent[1]
        mic_remoto = e_remoto(mic_nome)
        self.v_mic.config(text=mic_nome)
        if mic_remoto:
            self.n_mic.config(text="vem do headset do notebook", fg=VERDE)
        elif remoto:
            self.n_mic.config(text="local do PC - nao e o seu headset", fg=VERMELHO)
        else:
            self.n_mic.config(text="dispositivo local", fg=FRACO)

        pico = self.audio.pico
        self.audio.pico *= 0.85
        larg = max(1, self.cv.winfo_width())
        self.cv.delete("all")
        n = int(min(1.0, pico) * larg)
        if n > 0:
            self.cv.create_rectangle(
                0, 0, n, 16, width=0,
                fill=VERMELHO if pico > 0.75 else (VERDE if pico > 0.02 else TRILHO))
        falando = pico > 0.02
        self.lb_pct.config(
            text="{}%  {}".format(int(min(1.0, pico) * 100),
                                  "CAPTANDO" if falando else "silencio"),
            fg=VERDE if falando else FRACO)

        sai_nome = self.sai[1]
        self.v_sai.config(text=sai_nome)
        if e_remoto(sai_nome):
            self.n_sai.config(text="vai para o headset do notebook", fg=VERDE)
        elif remoto:
            self.n_sai.config(text="toca no PC - voce nao vai ouvir", fg=AMARELO)
        else:
            self.n_sai.config(text="dispositivo local", fg=FRACO)

        if self.proc:
            if self.proc.poll() is None:
                self.lb_proc.config(text=self.ultima_linha or "rodando", fg=VERDE)
            else:
                self.lb_proc.config(text="encerrou: " + (self.ultima_linha or "?"),
                                    fg=AMARELO)
                self.parar_proc()

        if not remoto:
            self.lb_status.config(text="Sessao local. Clique em conectar por RDP.",
                                  fg=FRACO)
        elif mic_remoto and e_remoto(sai_nome):
            self.lb_status.config(text="TUDO CERTO - MicroSIP e Teams usam seu headset.",
                                  fg=VERDE)
        elif mic_remoto:
            self.lb_status.config(text="Microfone OK, mas o som do PC nao vem para voce.",
                                  fg=AMARELO)
        else:
            self.lb_status.config(
                text="O padrao nao e o audio remoto. Som -> Entrada: "
                     "escolha 'Redirecionamento de Audio Remoto'.", fg=VERMELHO)

        self.raiz.after(60, self.tick)

    def fechar(self):
        self.parar_proc()
        self.audio.parar.set()
        self.raiz.destroy()


if __name__ == "__main__":
    raiz = tk.Tk()
    Painel(raiz)
    raiz.mainloop()
