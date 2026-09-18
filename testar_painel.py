"""Testa o comportamento da janela: rolagem, encolhimento e secao expansivel.

Abre a janela por instantes e fecha sozinho. Rode com:  python testar_painel.py
"""
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import painel as P

falhas = []


def check(nome, cond, extra=""):
    print(("  OK    " if cond else "  FALHA ") + nome + ("   " + extra if extra else ""))
    if not cond:
        falhas.append(nome)


raiz = tk.Tk()
p = P.Painel(raiz)
raiz.update(); raiz.update_idletasks()

rol = p.area.master.master          # Frame interno -> Canvas -> Rolavel
cv = rol.canvas


def estado():
    raiz.update(); raiz.update_idletasks()
    bbox = cv.bbox("all")
    return (bbox[3] if bbox else 0), cv.winfo_height(), rol.barra.winfo_ismapped()


print("\n[1] a janela encolhe e a barra aparece")
conteudo, _, _ = estado()
check("minsize permite janela pequena", raiz.minsize() <= (320, 240),
      str(raiz.minsize()))

raiz.geometry("300x200")
c, v, barra = estado()
check("conteudo maior que a area visivel", c > v, "{}px > {}px".format(c, v))
check("barra de rolagem aparece", barra)

print("\n[2] rolagem")
cv.yview_moveto(0); raiz.update()
topo = cv.yview()[0]
cv.event_generate("<MouseWheel>", delta=-360)
raiz.update()
check("roda do mouse rola", cv.yview()[0] > topo,
      "{:.3f} -> {:.3f}".format(topo, cv.yview()[0]))

cv.yview_moveto(1.0); raiz.update()
check("da para chegar ao fim", cv.yview()[1] >= 0.999)

print("\n[3] secao 'fora de casa' recolhivel")
check("comeca recolhida", not p.aberto.get())
p.alterna_secao()
c_aberta, _, _ = estado()
check("expandir aumenta o conteudo", c_aberta > c, "{} -> {}".format(c, c_aberta))
p.alterna_secao()
c_fechada, _, _ = estado()
check("recolher volta ao tamanho de antes", c_fechada == c)

print("\n[4] janela grande dispensa a barra")
raiz.geometry("400x900")
_, _, barra_grande = estado()
check("barra some quando tudo cabe", not barra_grande)

p.audio.parar.set()
raiz.destroy()

print("\n" + ("FALHOU: " + ", ".join(falhas) if falhas else "TODOS OS TESTES PASSARAM"))
sys.exit(1 if falhas else 0)
