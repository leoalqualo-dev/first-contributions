"""Rastreador de passagens para a final da Libertadores 2026 (Montevidéu, 28/11).

Pesquisa no Google Flights (via biblioteca fast-flights) todas as combinações de
origens, destinos e datas do config.json, monta o ranking pelo custo TOTAL
(passagem + deslocamento até o aeroporto + traslado até Montevidéu), guarda o
histórico e avisa quando aparece algo mais barato.

Uso:
    python buscar.py                 # pesquisa tudo e atualiza relatório/histórico
    python buscar.py --rapido        # só MVD e só origens de ida-e-volta (teste rápido)
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fast_flights import FlightQuery, Passengers, create_query, get_flights

PASTA = Path(__file__).resolve().parent
ARQ_CONFIG = PASTA / "config.json"
ARQ_ESTADO = PASTA / "dados" / "estado.json"
ARQ_HISTORICO = PASTA / "dados" / "historico.csv"
ARQ_RELATORIO = PASTA / "RELATORIO.md"
ARQ_ALERTA = PASTA / "dados" / "alerta.md"

DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


@dataclass
class Voo:
    """Um trecho (ou um ida-e-volta) encontrado no Google Flights."""

    origem: str
    destino: str
    data: str
    preco: int
    cias: list[str]
    partida: datetime | None
    chegada: datetime | None
    paradas: int
    duracao_min: int
    link: str


@dataclass
class Opcao:
    """Uma forma completa de ir e voltar, com custo total."""

    tipo: str  # "trechos separados" ou "ida e volta"
    descricao: str
    preco_passagens: int
    custo_extra: int
    ida: Voo
    volta: Voo | None = None
    chave: str = ""
    observacoes: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.preco_passagens + self.custo_extra


def carregar_config() -> dict:
    with open(ARQ_CONFIG, encoding="utf-8") as f:
        return json.load(f)


def _datahora(sd) -> datetime | None:
    try:
        return datetime(*sd.date, *sd.time)
    except (TypeError, ValueError):
        return None


def _formatar_data(iso: str) -> str:
    d = datetime.strptime(iso, "%Y-%m-%d")
    return f"{DIAS_SEMANA[d.weekday()]} {d:%d/%m}"


def _formatar_hora(dt: datetime | None) -> str:
    return f"{dt:%d/%m %H:%M}" if dt else "?"


def _reais(v: int) -> str:
    return "R$ " + f"{v:,.0f}".replace(",", ".")


def pesquisar(cfg: dict, trechos: list[tuple[str, str, str]], tipo: str) -> list[Voo]:
    """Faz uma busca no Google Flights e devolve os voos encontrados."""
    consultas = [FlightQuery(date=d, from_airport=o, to_airport=de) for o, de, d in trechos]
    q = create_query(
        flights=consultas,
        trip=tipo,
        passengers=Passengers(adults=cfg["passageiros_adultos"]),
        language="pt-BR",
        currency=cfg["moeda"],
        max_stops=cfg.get("max_paradas"),
    )
    resultado = get_flights(q)
    voos = []
    o, de, d = trechos[0]
    for r in resultado:
        if not r.flights or not r.price:
            continue
        voos.append(
            Voo(
                origem=o,
                destino=de,
                data=d,
                preco=int(r.price),
                cias=list(r.airlines),
                partida=_datahora(r.flights[0].departure),
                chegada=_datahora(r.flights[-1].arrival),
                paradas=len(r.flights) - 1,
                duracao_min=sum(s.duration or 0 for s in r.flights),
                link=q.url(),
            )
        )
    return voos


def melhor_voo(voos: list[Voo], chegada_limite: datetime | None = None, horas_extra: float = 0) -> Voo | None:
    """O voo mais barato que chega a tempo (considerando o traslado até Montevidéu)."""
    validos = []
    for v in voos:
        if chegada_limite and v.chegada and v.chegada + timedelta(hours=horas_extra) > chegada_limite:
            continue
        validos.append(v)
    return min(validos, key=lambda v: (v.preco, v.duracao_min), default=None)


def coletar(cfg: dict, rapido: bool) -> tuple[list[Opcao], int, int]:
    origens = {o["codigo"]: o for o in cfg["origens"]}
    destinos = {d["codigo"]: d for d in cfg["destinos"]}
    if rapido:
        origens = {k: v for k, v in origens.items() if k in cfg["origens_ida_e_volta"]}
        destinos = {k: v for k, v in destinos.items() if k == "MVD"}
    limite = datetime.fromisoformat(cfg["chegada_limite"])
    pausa = cfg.get("pausa_entre_buscas_segundos", 2)

    buscas_ok = buscas_falhas = 0

    def tentar(trechos, tipo):
        nonlocal buscas_ok, buscas_falhas
        rotulo = " + ".join(f"{o}→{d} {dt}" for o, d, dt in trechos)
        for tentativa in range(2):
            try:
                voos = pesquisar(cfg, trechos, tipo)
                buscas_ok += 1
                print(f"  ok  {rotulo}: {len(voos)} voos", flush=True)
                time.sleep(pausa)
                return voos
            except Exception as e:  # noqa: BLE001 - qualquer falha de rede/parse não pode parar tudo
                erro = e
                time.sleep(pausa * (tentativa + 2))
        buscas_falhas += 1
        print(f"  ERRO {rotulo}: {type(erro).__name__}: {erro}", flush=True)
        return []

    # 1) Trechos só de ida: cada origem → cada destino em cada data de ida
    print("Pesquisando trechos de IDA...")
    idas: list[tuple[Voo, dict, dict]] = []
    for o in origens.values():
        for de in destinos.values():
            for d in cfg["datas_ida"]:
                v = melhor_voo(tentar([(o["codigo"], de["codigo"], d)], "one-way"), limite, de["horas_extra"])
                if v:
                    idas.append((v, o, de))

    # 2) Trechos só de volta
    print("Pesquisando trechos de VOLTA...")
    voltas: list[tuple[Voo, dict, dict]] = []
    for o in origens.values():
        for de in destinos.values():
            for d in cfg["datas_volta"]:
                v = melhor_voo(tentar([(de["codigo"], o["codigo"], d)], "one-way"))
                if v:
                    voltas.append((v, o, de))

    opcoes: list[Opcao] = []

    # Combina qualquer ida com qualquer volta (pode ir pelo Rio e voltar para Guarulhos, por ex.)
    for vi, oi, di in idas:
        for vv, ov, dv in voltas:
            extra = round((oi["custo_deslocamento"] + ov["custo_deslocamento"]) / 2
                          + (di["custo_extra"] + dv["custo_extra"]) / 2)
            obs = []
            if di["codigo"] != "MVD":
                obs.append(f"ida via {di['cidade']}")
            if dv["codigo"] != "MVD":
                obs.append(f"volta via {dv['cidade']}")
            if oi["codigo"] != ov["codigo"]:
                obs.append(f"sai de {oi['codigo']} e volta para {ov['codigo']}")
            opcoes.append(Opcao(
                tipo="trechos separados",
                descricao=f"{vi.origem}→{vi.destino} {_formatar_data(vi.data)} / {vv.origem}→{vv.destino} {_formatar_data(vv.data)}",
                preco_passagens=vi.preco + vv.preco,
                custo_extra=extra,
                ida=vi,
                volta=vv,
                chave=f"OW|{vi.origem}-{vi.destino}-{vi.data}|{vv.origem}-{vv.destino}-{vv.data}",
                observacoes=obs,
            ))

    # 3) Ida e volta no mesmo bilhete (só para algumas origens, e só Montevidéu)
    print("Pesquisando IDA E VOLTA no mesmo bilhete...")
    for cod in cfg["origens_ida_e_volta"]:
        o = origens.get(cod)
        if not o:
            continue
        for di in cfg["datas_ida"]:
            for dv in cfg["datas_volta"]:
                v = melhor_voo(tentar([(cod, "MVD", di), ("MVD", cod, dv)], "round-trip"), limite)
                if v:
                    opcoes.append(Opcao(
                        tipo="ida e volta",
                        descricao=f"{cod}⇄MVD ida {_formatar_data(di)} / volta {_formatar_data(dv)}",
                        preco_passagens=v.preco,
                        custo_extra=o["custo_deslocamento"],
                        ida=v,
                        chave=f"RT|{cod}-MVD|{di}|{dv}",
                    ))

    opcoes.sort(key=lambda op: (op.total, op.ida.duracao_min))
    return opcoes, buscas_ok, buscas_falhas


def carregar_estado() -> dict:
    if ARQ_ESTADO.exists():
        return json.loads(ARQ_ESTADO.read_text(encoding="utf-8"))
    return {"melhor_total": None, "melhor_descricao": None, "precos": {}, "execucoes": 0}


def analisar(cfg: dict, opcoes: list[Opcao], estado: dict) -> tuple[list[str], list[str]]:
    """Compara com a execução anterior. Devolve (motivos de alerta, variações relevantes)."""
    alerta_cfg = cfg["alerta"]
    motivos, variacoes = [], []
    if not opcoes:
        return motivos, variacoes

    melhor = opcoes[0]
    anterior = estado.get("melhor_total")
    if anterior is None:
        motivos.append(f"Primeira pesquisa: melhor opção encontrada custa {_reais(melhor.total)} no total.")
    else:
        queda = anterior - melhor.total
        if queda > 0 and (queda >= alerta_cfg["queda_reais"] or queda / anterior * 100 >= alerta_cfg["queda_percentual"]):
            motivos.append(f"NOVO RECORDE: {_reais(melhor.total)} (antes o melhor era {_reais(anterior)}, caiu {_reais(queda)}).")
    alvo = alerta_cfg.get("preco_alvo")
    if alvo and melhor.total <= alvo and (anterior is None or anterior > alvo):
        motivos.append(f"Atingiu o preço-alvo de {_reais(alvo)}!")

    # Variações por rota, entre esta execução e a anterior
    precos_antes = estado.get("precos", {})
    for op in opcoes[:60]:
        antes = precos_antes.get(op.chave)
        if antes and antes != op.total:
            pct = (op.total - antes) / antes * 100
            if abs(pct) >= alerta_cfg["queda_percentual"]:
                seta = "📉 caiu" if pct < 0 else "📈 subiu"
                variacoes.append(f"{seta} {abs(pct):.0f}%: {op.descricao} — {_reais(antes)} → {_reais(op.total)}")
    return motivos, variacoes


def salvar(opcoes: list[Opcao], estado: dict, agora: datetime) -> None:
    ARQ_ESTADO.parent.mkdir(exist_ok=True)
    if opcoes:
        melhor = opcoes[0]
        if estado.get("melhor_total") is None or melhor.total < estado["melhor_total"]:
            estado["melhor_total"] = melhor.total
            estado["melhor_descricao"] = melhor.descricao
            estado["melhor_quando"] = agora.isoformat(timespec="minutes")
    estado["precos"] = {op.chave: op.total for op in opcoes}
    estado["execucoes"] = estado.get("execucoes", 0) + 1
    estado["ultima_execucao"] = agora.isoformat(timespec="minutes")
    ARQ_ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")

    novo = not ARQ_HISTORICO.exists()
    with open(ARQ_HISTORICO, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if novo:
            w.writerow(["quando", "posicao", "tipo", "descricao", "passagens", "extras", "total", "cias"])
        for i, op in enumerate(opcoes[:10], 1):
            cias = sorted(set(op.ida.cias + (op.volta.cias if op.volta else [])))
            w.writerow([agora.isoformat(timespec="minutes"), i, op.tipo, op.descricao,
                        op.preco_passagens, op.custo_extra, op.total, "/".join(cias)])


def _linha_voo(v: Voo) -> str:
    paradas = "direto" if v.paradas == 0 else f"{v.paradas} parada(s)"
    h, m = divmod(v.duracao_min, 60)
    return (f"{v.origem}→{v.destino} · {', '.join(v.cias)} · sai {_formatar_hora(v.partida)} "
            f"chega {_formatar_hora(v.chegada)} · {paradas} · {h}h{m:02d} · {_reais(v.preco)}")


def montar_relatorio(cfg, opcoes, estado, motivos, variacoes, agora, ok, falhas) -> str:
    L = [
        "# 🐷💚 Passagens para a final da Libertadores — Montevidéu, 28/11/2026",
        "",
        f"Última pesquisa: **{agora:%d/%m/%Y %H:%M}** (horário de Brasília) · "
        f"{ok} buscas ok, {falhas} com erro · {cfg['passageiros_adultos']} adulto(s)",
        "",
        "Total = passagens + deslocamento até o aeroporto de saída + traslado até Montevidéu "
        "(valores do `config.json`). Preços do Google Flights; confira sempre no site da companhia antes de comprar.",
        "",
    ]
    if estado.get("melhor_total"):
        L += [f"🏆 Melhor total já visto: **{_reais(estado['melhor_total'])}** — {estado['melhor_descricao']} "
              f"(em {estado.get('melhor_quando', '?')})", ""]
    if motivos:
        L += ["## 🚨 Alertas", ""] + [f"- {m}" for m in motivos] + [""]
    if variacoes:
        L += ["## Variações desde a última pesquisa", ""] + [f"- {v}" for v in variacoes[:20]] + [""]

    L += ["## Top 15 opções agora", "",
          "| # | Total | Passagens | Extras | Tipo | Roteiro | Obs. |",
          "|---|---|---|---|---|---|---|"]
    for i, op in enumerate(opcoes[:15], 1):
        L.append(f"| {i} | **{_reais(op.total)}** | {_reais(op.preco_passagens)} | {_reais(op.custo_extra)} | "
                 f"{op.tipo} | {op.descricao} | {'; '.join(op.observacoes) or '—'} |")

    L += ["", "## Detalhes das 5 melhores", ""]
    for i, op in enumerate(opcoes[:5], 1):
        L.append(f"**{i}. {op.descricao} — {_reais(op.total)}**")
        L.append(f"- Ida: {_linha_voo(op.ida)} · [abrir no Google Flights]({op.ida.link})")
        if op.volta:
            L.append(f"- Volta: {_linha_voo(op.volta)} · [abrir no Google Flights]({op.volta.link})")
        else:
            L.append("- (preço já inclui a volta — veja as opções de volta no link)")
        L.append("")

    # Melhor preço por data de ida: ajuda a decidir o dia
    L += ["## Mais barato por dia de ida", "", "| Ida | Melhor total | Roteiro |", "|---|---|---|"]
    for d in cfg["datas_ida"]:
        do_dia = [op for op in opcoes if op.ida.data == d]
        if do_dia:
            L.append(f"| {_formatar_data(d)} | {_reais(do_dia[0].total)} | {do_dia[0].descricao} |")
        else:
            L.append(f"| {_formatar_data(d)} | — | nada encontrado |")
    L.append("")
    return "\n".join(L)


def notificar_telegram(texto: str) -> None:
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    dados = urllib.parse.urlencode({"chat_id": chat, "text": texto[:4000], "disable_web_page_preview": "true"}).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=dados, timeout=20)
        print("Alerta enviado no Telegram.")
    except Exception as e:  # noqa: BLE001
        print(f"Falha ao enviar Telegram: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rapido", action="store_true", help="pesquisa reduzida (teste)")
    args = ap.parse_args()

    cfg = carregar_config()
    agora = datetime.now(timezone(timedelta(hours=-3))).replace(tzinfo=None)  # horário de Brasília
    opcoes, ok, falhas = coletar(cfg, args.rapido)

    if not opcoes:
        print(f"Nenhuma opção encontrada ({ok} buscas ok, {falhas} com erro). Nada foi salvo.")
        return 1

    estado = carregar_estado()
    motivos, variacoes = analisar(cfg, opcoes, estado)
    salvar(opcoes, estado, agora)
    relatorio = montar_relatorio(cfg, opcoes, estado, motivos, variacoes, agora, ok, falhas)
    ARQ_RELATORIO.write_text(relatorio, encoding="utf-8")

    print()
    print(f"Melhor agora: {_reais(opcoes[0].total)} — {opcoes[0].descricao}")
    for i, op in enumerate(opcoes[1:5], 2):
        print(f"  {i}. {_reais(op.total)} — {op.descricao}")

    if ARQ_ALERTA.exists():
        ARQ_ALERTA.unlink()
    if motivos or any(v.startswith("📉") for v in variacoes):
        top = "\n".join(f"{i}. {_reais(op.total)} — {op.descricao}" for i, op in enumerate(opcoes[:5], 1))
        quedas = "\n".join([v for v in variacoes if v.startswith("📉")][:10])
        texto = "\n\n".join(x for x in ["\n".join(motivos), quedas, "Top 5 agora:\n" + top] if x)
        ARQ_ALERTA.write_text(texto + "\n\nRelatório completo: passagens-libertadores/RELATORIO.md\n", encoding="utf-8")
        print("\n🚨 ALERTA:\n" + texto)
        notificar_telegram("🐷💚 Passagens final Libertadores\n\n" + texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
