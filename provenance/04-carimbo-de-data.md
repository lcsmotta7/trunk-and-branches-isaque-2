# Carimbo de data pública: tese "Tronco e Ramos", Etapa 1

Autor: Lucas Alves Motta
Carimbado em 11/11/2026, por volta das 13h50 (horário de Brasília)

## O que foi carimbado

- **Arquivo:** `03-manifesto-sha256-etapa-1.txt`. Ele lista o SHA-256 de 23 arquivos (a tese, o desenho, a linha do tempo, os scripts, os recibos, os ramos e o modelo juiz) e o SHA-256 do próprio manifesto em .md.
- **SHA-256 do manifesto carimbado:** `79602f29a07b8b336e29c887ac1723aa9aea5b710605c67d42b21bc2558be5dd`
- **Prova:** `03-manifesto-sha256-etapa-1.txt.ots`, com 910 bytes, no formato OpenTimestamps.

## Calendários que receberam o registro

Todos responderam com sucesso. A prova traz um compromisso de cada um:

1. alice.btc.calendar.opentimestamps.org
2. bob.btc.calendar.opentimestamps.org
3. finney.calendar.eternitywall.com
4. btc.calendar.catallaxy.com

Os calendários só receberam um hash derivado com um número aleatório (*nonce*). Nenhum conteúdo dos arquivos saiu da máquina.

## Como qualquer pessoa confere

1. Baixar o manifesto `.txt` e o `.ots`.
2. Rodar `ots verify 03-manifesto-sha256-etapa-1.txt.ots`, com o cliente oficial OpenTimestamps.
3. Conferir que cada arquivo publicado gera o SHA-256 listado no manifesto.

## Situação

- **Agora:** a prova está **pendente**. Os calendários guardaram o registro e vão incluí-lo numa transação do Bitcoin.
- **Algumas horas depois:** a prova pode ser **completada** (`ots upgrade`). Aí ela passa a apontar para um bloco do Bitcoin e não depende mais de nenhum calendário.

## Regra

Os arquivos `02-tese-tronco-e-ramos-etapa-1.md` e `03-manifesto-sha256-etapa-1.md` **não podem mais ser editados**. Qualquer mudança quebra a impressão digital carimbada. Correções viram uma versão nova, com manifesto e carimbo novos.

## Prova completada no Bitcoin

Completada em 11/11/2026 às 22:08 (horário de Brasília). Os 4 calendários completaram e cada bloco foi conferido na API pública blockstream.info. Vale o bloco mais antigo: é a data mais cedo provada.

| Calendário | Bloco | Data e hora do bloco (Brasília) | Hash do bloco |
|---|---|---|---|
| alice.btc.calendar.opentimestamps.org | 975458 | 11/11/2026 14:41 | 00000000000000000000f9ecaff2000a3ef56bcec68bf3ebb69bb31a740c6a2c |
| bob.btc.calendar.opentimestamps.org | 975462 | 11/11/2026 15:08 | 00000000000000000000c8372e1626ff54e8d992e348103dec0af031af1ce4b2 |
| finney.calendar.eternitywall.com | 975464 | 11/11/2026 15:32 | 0000000000000000000138036994e1733914b51591f3ad91a8e6b3d349fa7dec |
| btc.calendar.catallaxy.com | 975469 | 11/11/2026 16:56 | 000000000000000000010334386c4356e317f2128606b51bba9219760fdb9923 |

- Conferência: hash no `.ots` confere com o manifesto `.txt` (True); `.ots` lido por inteiro (5124 de 5124 bytes); 4 linhas `bitcoin`.
- A versão pendente foi guardada como `03-manifesto-sha256-etapa-1.txt.pendente.ots`.
