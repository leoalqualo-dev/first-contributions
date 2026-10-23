# 🐷💚 Rastreador de passagens: final da Libertadores 2026

**Final:** sábado, 28/11/2026, Estádio Centenário, Montevidéu.

O script pesquisa o Google Flights para **todas as combinações** abaixo e ordena pelo **custo total**:

| O quê | Padrão (edite em `config.json`) |
|---|---|
| Datas de ida | 25, 26, 27 e 28/11 (no dia 28 só valem voos que chegam até 13h) |
| Datas de volta | 29 e 30/11 |
| Aeroportos de saída | GRU, CGH, VCP, GIG, SDU, CWB, FLN, POA, CNF, BSB |
| Aeroportos de chegada | Montevidéu (MVD), Punta del Este (PDP, +ônibus), Buenos Aires AEP/EZE (+barco) |
| Formatos | trechos separados (pode ir por um aeroporto e voltar por outro) **e** ida-e-volta no mesmo bilhete |

**Custo total** = passagens + `custo_deslocamento` (de casa até o aeroporto, ex.: ônibus SP→Rio)
+ `custo_extra` (do aeroporto até Montevidéu, ex.: Buquebus saindo de Buenos Aires).
Assim, "voar do Rio é mais barato" só aparece no topo se compensar **mesmo** a viagem até o Rio.

## Como usar

### Opção 1: automático no GitHub (recomendado)
O workflow `.github/workflows/passagens-libertadores.yml` roda **a cada 6 horas**, atualiza
[`RELATORIO.md`](RELATORIO.md) e `dados/historico.csv`, e **abre/comenta uma issue** quando:
- aparece um novo recorde de preço (queda ≥ 5% ou ≥ R$ 100 frente ao melhor já visto);
- o total fica abaixo do `preco_alvo` (R$ 3.500 ida e volta);
- alguma rota cai ≥ 5% desde a pesquisa anterior.

O GitHub manda e-mail a cada comentário na issue. Para rodar na hora: aba **Actions** →
*Passagens final Libertadores* → **Run workflow**.

> Workflows agendados só rodam a partir do branch padrão (`main`), então é preciso fazer merge deste branch.

**Alerta no Telegram (opcional):** crie um bot com o @BotFather, pegue seu chat id (ex.: @userinfobot)
e cadastre os secrets `TELEGRAM_TOKEN` e `TELEGRAM_CHAT_ID` em *Settings → Secrets and variables → Actions*.

### Opção 2: no seu computador
```bash
cd passagens-libertadores
pip install -r requirements.txt
python buscar.py            # pesquisa completa (~270 buscas, 15-20 min)
python buscar.py --rapido   # teste rápido
```

## Dicas de torcedor
- **Ingresso primeiro:** sem ingresso da cota do Palmeiras não adianta passagem. Prefira tarifas com remarcação.
- **Buenos Aires + barco:** Buquebus/Colonia Express em dia de final esgota rápido; ajuste `custo_extra` com o preço real.
- **Porto Alegre:** de POA também há ônibus direto para Montevidéu (~12h), uma alternativa a voar.
- Os preços vêm do Google Flights e podem mudar a qualquer momento; confira no site da companhia antes de comprar.
