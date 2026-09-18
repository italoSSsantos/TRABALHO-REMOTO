# Microfone do notebook no PC do trabalho

## Comece por aqui: em casa, use RDP — não precisa de nada disso

Levantamento feito em 18/09/2026 no notebook `ULTRON_LEN` e no PC `SD-MSP35`:

| | |
|---|---|
| PC | `SD-MSP35`, **192.168.0.244**, Windows 11 **Pro**, domínio `msp.ti` |
| Notebook | `ULTRON_LEN`, 192.168.0.100 — **mesma rede local** |
| Porta 3389 (RDP) | **aberta** a partir do notebook |
| Redirecionamento de microfone | **sem política bloqueando** |

Ou seja: o PC está na sua casa, na mesma rede. O **RDP leva o microfone nativamente**,
coisa que o Chrome Remote Desktop não faz. Isso dispensa o AudioLink, o Stereo Mix, a
separação de saídas e o risco de eco — tudo de uma vez.

**Dê dois cliques em `PC DO TRABALHO (com microfone).rdp`.** Já vai configurado com:

- `audiocapturemode:i:1` — seu microfone vira o microfone do PC
- `audiomode:i:0` — o som do PC toca no seu headset
- `camerastoredirect` — a webcam do notebook também passa, pra videochamada

No PC, o MicroSIP e o Teams passam a ver o headset do notebook como um microfone
comum. Não precisa escolher "Mixagem estéreo" nem mexer em saída de áudio.

**Duas diferenças em relação ao Chrome Remote Desktop:**

1. O RDP **bloqueia a tela do PC** enquanto você está conectado (o CRD compartilha a
   sessão). Trabalhando remoto isso não atrapalha, mas se alguém for usar o PC
   fisicamente, vai precisar fazer login de novo.
2. Só funciona **dentro da sua rede**. Fora de casa o PC fica atrás do NAT e o RDP não
   alcança — aí você volta pro Chrome Remote Desktop, e é onde entra o AudioLink abaixo.

Se o login por RDP for recusado, é permissão: seu usuário precisa estar no grupo
"Usuários da Área de Trabalho Remota" do PC. Aí sim vale um chamado pro TI — é uma
liberação de permissão, não instalação de software.

---

# AudioLink — plano B, para quando estiver fora de casa

Faz o microfone do headset que está **no notebook** aparecer no **PC** como se fosse
um microfone plugado lá. Assim você atende ligações no PC (Teams, softphone, discador,
Meet, o que for) falando pelo headset do notebook.

O som **do PC pra você** já vem pelo Chrome Remote Desktop — esta ferramenta resolve o
que falta, que é o caminho contrário.

```
NOTEBOOK                                       PC (a máquina que você acessa)
────────                                       ─────────────────────────────
headset  ──► audiolink send ──► UDP ──► audiolink recv ──► "CABLE Input"
                                                                  │
                                                           "CABLE Output"
                                                                  │
                                                     Teams / softphone usa
                                                     isso como MICROFONE
```

---

## Por que precisa do VB-Cable

Um programa no Windows só consegue usar como microfone algo que o sistema
registre como *dispositivo de entrada*. Um script Python não pode criar um desses —
isso exige um driver de áudio assinado digitalmente.

O **VB-Cable** é exatamente esse driver, pronto e gratuito. Ele cria um par:

- **CABLE Input** — uma "saída" onde o AudioLink despeja a sua voz
- **CABLE Output** — a "entrada" correspondente, que o Teams enxerga como microfone

É um cabo de áudio virtual: o que entra de um lado sai do outro.

---

## Instalação

### 1. Nos dois computadores

- [Python](https://python.org/downloads) — na instalação, **marque "Add Python to PATH"**
- Rode `1 - INSTALAR (nos dois PCs).bat`

### 2. Só no PC (a máquina que recebe)

- Baixe o **VB-Cable** em https://vb-audio.com/Cable/ (pacote `VBCABLE_Driver_Pack45.zip`, ~1,3 MB)
- **Extraia o zip** antes de instalar — rodar de dentro do zip falha
- Botão direito no setup de 64 bits (`VBCABLE_Setup_x64.exe`) → **Executar como administrador**
- **Reinicie o Windows.** É driver de sistema; sem reiniciar ele não aparece
- Confirme rodando `VER DISPOSITIVOS DE AUDIO.bat` — deve aparecer `CABLE Input` e `CABLE Output`

> É donationware: o download é gratuito e funciona sem pagar nada. A página tem um
> campo de doação opcional, com valor que você mesmo define. Suporta Windows XP até o 11.

---

## Se você não tem admin no PC

O VB-Cable é driver de sistema: **exige administrador**, sem contorno. Se o PC é da
empresa e você não tem essa permissão, rode primeiro:

```
DIAGNOSTICO - rodar no PC.ps1
```

Ele diz qual dos três caminhos serve pro seu PC.

### Configuração já medida no SD-MSP35

Rodado e confirmado no PC — a separação anti-eco já existe sem mexer em nada, porque
o Fuxi-H6 é uma placa USB separada que o Stereo Mix não enxerga:

```
No PC:        python audiolink.py recv --out 10
No notebook:  python audiolink.py send --to 192.168.0.244
```

| No MicroSIP e no Teams | Escolher |
|---|---|
| Microfone | **Mixagem estéreo (Realtek)** |
| Saída / alto-falante | **Alto-falantes (Fuxi-H6)** |

Medição que sustenta isso: a Mixagem estéreo capta a Realtek a `2403x` o nível de
ruído, e o Fuxi-H6 a `0x` — ou seja, o que tocar no Fuxi-H6 não volta pra ligação.

> Enquanto isso estiver em uso, a **Realtek vira saída exclusiva do AudioLink**.
> Qualquer outro programa que tocar som por ela entra na ligação. Mantenha tudo
> apontado pro Fuxi-H6.
>
> O HDMI não serve aqui: o "Áudio Intel(R) para telas" existe, mas não há monitor
> com alto-falante ligado.

### Caminho A — o PC já tem "Mixagem estéreo" (Stereo Mix)

É um microfone que **já existe** na maioria das placas Realtek e captura o que está
tocando no PC. Habilitar não pede admin. O AudioLink toca a sua voz numa saída, e o
Teams usa a Mixagem estéreo como microfone.

O porém: ela capta **tudo** que toca, inclusive a voz da pessoa do outro lado — que
então se ouve com atraso. Pra evitar isso o PC precisa de **duas saídas de áudio
independentes**, e aí você separa os caminhos (o diagnóstico confirma se dá):

| Programa | Saída de áudio | Por quê |
|---|---|---|
| AudioLink | a placa que a Mixagem estéreo escuta | é o que vira seu microfone |
| Teams / softphone | **outra** placa | fica fora da Mixagem estéreo, sem eco |

No Windows 11 isso se ajusta em **Configurações → Sistema → Som → Mixer de volume**,
que deixa escolher a saída de cada programa separadamente.

### Caminho B — pedir ao TI

É o caminho confiável. Texto pronto pra enviar:

> Preciso instalar o **VB-CABLE Virtual Audio Device** na minha estação.
>
> É um driver de áudio gratuito da VB-Audio (vb-audio.com), ~1,3 MB, usado
> amplamente no mercado. Ele cria um dispositivo de áudio virtual local.
>
> **Motivo:** trabalho remoto acessando esta máquina, e o acesso remoto não
> transporta microfone. Sem isso não consigo atender ligações pelo headset.
>
> Não abre portas de rede, não envia dados pra fora e não altera o áudio
> existente — só adiciona um dispositivo virtual. Instalação pede admin e
> um reinício.

### Caminho C — atender a ligação no próprio notebook

Se o discador tiver versão web ou aplicativo de celular, atender por ali resolve o
problema inteiro sem precisar de nada disso. Vale conferir antes de partir pros outros.

---

## Usando no dia a dia

**No PC** (deixe rodando): `2 - PC - RECEBER MICROFONE.bat`

Ele mostra os IPs do PC. Anote o da sua rede (`192.168.x.x`).

**No notebook**: `3 - NOTEBOOK - ENVIAR MICROFONE.bat`

Pede o IP do PC na primeira vez e guarda em `ip_do_pc.txt`. Nas próximas, abre direto.

**No programa de ligação (dentro do PC)**, em configurações de áudio:

| | |
|---|---|
| Microfone / Entrada | **CABLE Output (VB-Audio Virtual Cable)** |
| Alto-falante / Saída | deixe o normal do PC — é o que o CRD te entrega |

> Se o programa tiver teste de microfone, fale no headset e veja a barrinha mexer.
> A janela do notebook também mostra o nível: `mic [########------------]`.

---

## Usando fora de casa

Na rede local o notebook fala direto com o PC. Fora de casa não existe esse caminho —
o roteador do PC bloqueia. A solução limpa é o **Tailscale**, que monta uma rede
privada criptografada entre suas máquinas, sem mexer em roteador.

1. Instale o [Tailscale](https://tailscale.com/download) nos dois computadores
2. Faça login com a mesma conta nos dois (o plano gratuito cobre isso de sobra)
3. Rode `2 - PC - RECEBER MICROFONE.bat` no PC e use o IP `100.x.x.x` que aparecer

Funciona igual, de qualquer lugar. Pra trocar entre o IP de casa e o do Tailscale:

```
"3 - NOTEBOOK - ENVIAR MICROFONE.bat" --trocar
```

### Economizando banda fora de casa

No padrão o áudio vai em 48 kHz, que gasta **~780 kbps** de upload constante. Na rede
de casa isso não é nada, mas em 4G ou Wi-Fi de hotel pode não caber. Para voz, 16 kHz
já é mais do que suficiente (é mais nítido que a banda do telefone) e gasta **~260 kbps**:

```
PC:        python audiolink.py recv --hz 16000
NOTEBOOK:  python audiolink.py send --to 100.x.x.x --hz 16000
```

O `--hz` tem que ser **igual nos dois lados** — se você errar, o programa avisa na tela
qual lado está em qual taxa, em vez de sair um áudio distorcido.

> **Não** abra a porta 50505 no roteador pra usar sem Tailscale. O tráfego é PCM sem
> criptografia, e o `--secret` só descarta pacote aleatório — não protege contra
> ninguém de verdade. Dentro do Tailscale tudo já vai criptografado.

---

## Ajustes

Passe as opções direto pro `audiolink.py`, ou depois do nome do `.bat`:

| Opção | Pra que serve |
|---|---|
| `--jitter 20` | Menos atraso, mas pica se a rede oscilar. Padrão 40ms |
| `--jitter 80` | Mais atraso, aguenta Wi-Fi ruim |
| `--mic "Headset"` | Escolhe o microfone pelo nome, se pegar o errado |
| `--out "CABLE Input"` | Escolhe a saída no PC (é o padrão) |
| `--port 50505` | Troca a porta UDP, se der conflito |
| `--secret minhasenha` | Tem que ser **igual nos dois lados** |
| `--hz 16000` | Economiza banda (~260 kbps em vez de ~780). **Igual nos dois lados** |
| `--duplex` | Também traz o som do PC. Só use se o áudio do CRD não servir |

Exemplos:

```
python audiolink.py list
python audiolink.py send --to 192.168.0.50 --mic "Headset" --jitter 20
python audiolink.py recv --jitter 60
```

Pra ver os nomes exatos dos dispositivos: `VER DISPOSITIVOS DE AUDIO.bat`

---

## O que a janela mostra

**Notebook:**
```
   42s   mic [########------------]  enviados 100/s
```
`enviados 100/s` é o normal (um pacote a cada 10ms). A barra tem que mexer quando você fala.

**PC:**
```
   42s   recebidos 100/s  buffer  40ms   falhas 0
```
`falhas` subindo = rede instável, aumente o `--jitter`.

---

## Problemas comuns

**A barra do microfone não mexe**
O Windows está bloqueando. Configurações → Privacidade → Microfone → ligue
"Permitir que aplicativos da área de trabalho acessem seu microfone".
Se mexer mas pegar o mic errado, use `--mic "parte do nome"`.

**`recebidos 0/s` no PC**
O firewall está barrando. No PC, rode como administrador:
```
netsh advfirewall firewall add rule name="AudioLink" dir=in action=allow protocol=UDP localport=50505
```
Se for fora de casa, confirme que o Tailscale está conectado nos dois lados.

**Ninguém me ouve, mas os números estão certos**
O programa de ligação não está no `CABLE Output`. Vale também conferir em
Configurações → Sistema → Som → Configurações avançadas, se o app tem um
dispositivo próprio definido, sobrepondo o global.

**Voz picotada / robótica**
Aumente o buffer: `--jitter 80`. Se persistir, use cabo em vez de Wi-Fi no notebook.

**Eco — a pessoa se escuta**
O `CABLE Input` virou a saída padrão do Windows no PC. Ele tem que ficar só como
destino do AudioLink. Em Som → Saída, deixe o padrão nos alto-falantes normais.

**Muito atraso**
Baixe pra `--jitter 20` nos dois lados. Na rede local dá pra chegar em ~30ms no total.

**`Invalid device [PaErrorCode -9996]`**
O dispositivo não aceita a taxa que você pediu. Os dispositivos marcados com `*`
na lista (WASAPI) convertem sozinhos — prefira esses. Os `WDM-KS` são crus e só
funcionam na taxa nativa deles.

---

## Verificar se está tudo certo

```
python testar.py
```

Testa o protocolo de rede, o buffer anti-oscilação e a abertura dos dispositivos —
sem tocar som nenhum. Deve terminar com `TODOS OS TESTES PASSARAM`.

---

## Arquivos

| Arquivo | |
|---|---|
| `audiolink.py` | O programa |
| `testar.py` | Testes automatizados |
| `1 - INSTALAR (nos dois PCs).bat` | Instala as dependências |
| `2 - PC - RECEBER MICROFONE.bat` | Rode no PC |
| `3 - NOTEBOOK - ENVIAR MICROFONE.bat` | Rode no notebook |
| `VER DISPOSITIVOS DE AUDIO.bat` | Lista os dispositivos |
| `ip_do_pc.txt` | Criado sozinho, guarda o IP do PC |
