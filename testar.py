"""Testa o caminho de rede, o jitter buffer e a abertura dos streams reais."""
import socket, sys, time, threading
import numpy as np

sys.path.insert(0, r"C:\Users\italo\Desktop\TRABALHO REMOTO")
import audiolink as al

fails = []

def check(name, cond, extra=""):
    print(("  OK   " if cond else "  FALHA ") + name + ("  " + str(extra) if extra else ""))
    if not cond:
        fails.append(name)

# ---------------------------------------------------------------- 1. protocolo
print("\n[1] protocolo e rede (sem audio)")

tok = al.token_of("audiolink")
stats = al.new_stats()
peer = [None]

rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
rx_sock.settimeout(0.3)
rx_sock.bind(("127.0.0.1", 0))
port = rx_sock.getsockname()[1]

rcv = al.Receiver(rx_sock, 0, tok, stats, jitter_ms=40, learn_peer=peer)
threading.Thread(target=rcv._net_loop, daemon=True).start()

tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

def send_pkt(seq, tone=1000, token=tok, magic=al.MAGIC):
    t = np.arange(seq * al.BLOCK, (seq + 1) * al.BLOCK) / al.SAMPLERATE
    pcm = (np.sin(2 * np.pi * tone * t) * 8000).astype(np.int16)
    tx.sendto(al.HEADER.pack(magic, token, seq) + pcm.tobytes(), ("127.0.0.1", port))

for i in range(10):
    send_pkt(i)
time.sleep(0.4)

check("10 pacotes validos recebidos", stats["rx"] == 10, "rx=%d" % stats["rx"])
check("peer aprendido automaticamente", peer[0] is not None, peer[0])
check("buffer encheu", rcv.jb.depth() == 10, "depth=%d" % rcv.jb.depth())

# lixo e token errado devem ser rejeitados
tx.sendto(b"lixo aleatorio que nao e audio", ("127.0.0.1", port))
send_pkt(99, token=al.token_of("outro-segredo"))
send_pkt(98, magic=b"XXXX")
time.sleep(0.3)
check("trafego estranho rejeitado", stats["rejected"] == 3, "rejected=%d" % stats["rejected"])
check("rx nao subiu com lixo", stats["rx"] == 10, "rx=%d" % stats["rx"])

# perda de pacotes detectada
send_pkt(15)   # pulou 10..14 = 5 perdidos
time.sleep(0.3)
check("perda de pacote detectada", stats["lost"] == 5, "lost=%d" % stats["lost"])

# ------------------------------------------------------- 2. jitter buffer
print("\n[2] jitter buffer")

jb = al.JitterBuffer(target_blocks=4, max_blocks=16)
check("silencio antes de encher", jb.pop() is None)
for i in range(4):
    jb.push(np.full(al.BLOCK, i, dtype=np.int16))
b = jb.pop()
check("toca depois de encher", b is not None and b[0] == 0)
check("ordem preservada (FIFO)", jb.pop()[0] == 1)

# nao deixa a latencia crescer sem limite
jb2 = al.JitterBuffer(target_blocks=4, max_blocks=16)
for i in range(100):
    jb2.push(np.zeros(al.BLOCK, dtype=np.int16))
check("latencia limitada em max_blocks", jb2.depth() == 16, "depth=%d" % jb2.depth())
check("descartes contabilizados", jb2.dropped == 84, "dropped=%d" % jb2.dropped)

# underrun re-enche antes de voltar a tocar
jb3 = al.JitterBuffer(target_blocks=4, max_blocks=16)
for i in range(4):
    jb3.push(np.zeros(al.BLOCK, dtype=np.int16))
for _ in range(4):
    jb3.pop()
check("underrun detectado", jb3.pop() is None and jb3.underruns == 1)
jb3.push(np.zeros(al.BLOCK, dtype=np.int16))
check("re-enche antes de voltar", jb3.pop() is None, "nao deve tocar com 1 bloco so")

rcv.running = False
rx_sock.close()
tx.close()

# ------------------------------------------------- 3. streams de audio reais
print("\n[3] abertura dos dispositivos de audio reais")

import sounddevice as sd

mic = al.find_device(None, "input")
print("  microfone padrao: " + al.describe(mic))
captured = []
s = al.Sender(socket.socket(socket.AF_INET, socket.SOCK_DGRAM), mic, [None], tok, al.new_stats())
try:
    s.start()
    time.sleep(1.0)
    check("InputStream abriu a 48kHz", s.stream.active, "%d canal(is)" % s.channels)
    s.stop()
except Exception as e:
    check("InputStream abriu a 48kHz", False, e)

spk = al.find_device(None, "output")
print("  saida padrao:     " + al.describe(spk))
r2 = al.Receiver(socket.socket(socket.AF_INET, socket.SOCK_DGRAM), spk, tok, al.new_stats(), 40)
try:
    r2.start()          # sem pacotes chegando, toca so silencio
    time.sleep(1.0)
    check("OutputStream abriu a 48kHz", r2.stream.active, "%d canal(is)" % r2.channels)
    check("silencio limpo sem rede", r2.jb.underruns == 0)
    r2.stop()
except Exception as e:
    check("OutputStream abriu a 48kHz", False, e)

# ------------------------------------------- 4. integridade do audio na rede
print("\n[4] integridade do audio ponta a ponta")

s2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s2.settimeout(0.3)
s2.bind(("127.0.0.1", 0))
port2 = s2.getsockname()[1]

st2 = al.new_stats()
r3 = al.Receiver(s2, 0, tok, st2, jitter_ms=100)  # comporta os 20 blocos da rajada
threading.Thread(target=r3._net_loop, daemon=True).start()

tx2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
originais = []
for seq in range(20):
    t = np.arange(seq * al.BLOCK, (seq + 1) * al.BLOCK) / al.SAMPLERATE
    # voz sintetica: 440 Hz com um harmonico, amplitude de fala normal
    pcm = ((np.sin(2 * np.pi * 440 * t) + 0.3 * np.sin(2 * np.pi * 880 * t)) * 9000)
    pcm = pcm.astype(np.int16)
    originais.append(pcm)
    tx2.sendto(al.HEADER.pack(al.MAGIC, tok, seq) + pcm.tobytes(), ("127.0.0.1", port2))
time.sleep(0.5)

recebidos = [r3.jb.pop() for _ in range(20)]
recebidos = [b for b in recebidos if b is not None]

check("todos os blocos atravessaram", len(recebidos) == 20, "%d de 20" % len(recebidos))
if len(recebidos) == 20:
    iguais = all(np.array_equal(a, b) for a, b in zip(originais, recebidos))
    check("audio identico bit a bit (sem distorcao)", iguais)
    check("tamanho do bloco preservado", all(len(b) == al.BLOCK for b in recebidos))
    check("nenhuma amostra zerada/clipada", int(np.abs(np.concatenate(recebidos)).max()) > 10000)

pkt_size = al.HEADER.size + al.BLOCK * 2
check("pacote cabe numa MTU normal", pkt_size < 1400, "%d bytes" % pkt_size)
print("  banda usada: %.0f kbps por direcao" % (pkt_size * 100 * 8 / 1000))
print("  latencia do buffer no padrao (--jitter 40): ~40ms + ~20ms de placa = ~60ms")

r3.running = False
s2.close()
tx2.close()

# ---------------------------------------------------------------- resultado
print("\n" + ("FALHOU: " + ", ".join(fails) if fails else "TODOS OS TESTES PASSARAM"))
sys.exit(1 if fails else 0)
