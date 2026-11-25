"""Ciclo autônomo MAPE-K para redistribuição de carga (ADR 013). A = 0.

Monitor  -> coleta o estado dos alimentadores da subestação
Analyze  -> detecta alimentadores desenergizados e prevê carga com IA
Plan     -> escolhe o vizinho com mais folga para cada alimentador afetado
Execute  -> só aplica se TODOS os guardrails físicos aprovarem;
            senão, escala para o operador (humano no circuito)
Knowledge-> topologia e chaves de interligação (IBaseConhecimento)

A IA nunca decide sozinha o que é seguro: ela só prevê carga. A segurança
física é verificada por regras determinísticas (os guardrails).
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from domain.ports.autonomia import (IAtuadorRede, IBaseConhecimento, ICicloMapeK,
                                    IEstadoAlimentador, IExplicadorDecisao,
                                    IFonteEstadoRede, IGuardrail, IModeloPrevisaoCarga,
                                    IPlanoRedistribuicao, IPublicadorDecisoes)


@dataclass(frozen=True)
class Manobra:
    origem: str        # alimentador desenergizado
    destino: str       # alimentador vizinho que assume a carga
    chave_id: str      # chave de interligação a fechar
    carga_mw: float    # carga transferida (prevista pela IA)
    prioritario: bool


@dataclass
class PlanoRedistribuicao(IPlanoRedistribuicao):
    manobras: list = field(default_factory=list)
    carga_resultante_mw: dict = field(default_factory=dict)
    sem_destino: list = field(default_factory=list)


@dataclass
class Diagnostico:
    afetados: list            # estados desenergizados
    previsao_mw: dict         # alimentador_id -> carga prevista (IA)


# ---------------------------------------------------------------- M
class MonitorRede:
    def __init__(self, fonte: IFonteEstadoRede):
        self._fonte = fonte

    def coletar(self, subestacao_id: str) -> dict:
        return {e.alimentador_id: e for e in self._fonte.estados(subestacao_id)}


# ---------------------------------------------------------------- A
class AnalisadorRede:
    def __init__(self, modelo: IModeloPrevisaoCarga):
        self._modelo = modelo

    def analisar(self, estados: dict) -> Diagnostico:
        previsao = {}
        for estado in estados.values():
            try:
                previsao[estado.alimentador_id] = self._modelo.prever_mw(estado)
            except Exception:
                # Fallback: se o modelo falhar, usa a última carga medida
                previsao[estado.alimentador_id] = estado.carga_mw
        afetados = [e for e in estados.values() if not e.energizado]
        return Diagnostico(afetados=afetados, previsao_mw=previsao)


# ---------------------------------------------------------------- P
class PlanejadorRedistribuicao:
    def __init__(self, conhecimento: IBaseConhecimento):
        self._k = conhecimento

    def planejar(self, diag: Diagnostico, estados: dict) -> PlanoRedistribuicao:
        plano = PlanoRedistribuicao()
        # Cargas prioritárias (hospitais etc.) são religadas primeiro
        for afetado in sorted(diag.afetados, key=lambda e: not e.prioritario):
            carga = diag.previsao_mw[afetado.alimentador_id]
            melhor, chave, folga_max = None, None, 0.0
            for destino_id, chave_id in self._k.vizinhos(afetado.alimentador_id):
                destino = estados.get(destino_id)
                if destino is None or not destino.energizado:
                    continue
                atual = plano.carga_resultante_mw.get(destino_id, diag.previsao_mw[destino_id])
                folga = destino.capacidade_mw - atual
                if folga > folga_max:
                    melhor, chave, folga_max = destino_id, chave_id, folga
            if melhor is None:
                plano.sem_destino.append(afetado.alimentador_id)
                continue
            plano.manobras.append(Manobra(afetado.alimentador_id, melhor, chave,
                                          carga, afetado.prioritario))
            plano.carga_resultante_mw[melhor] = (
                plano.carga_resultante_mw.get(melhor, diag.previsao_mw[melhor]) + carga)
        return plano


# ---------------------------------------------------------- Guardrails
class GuardrailLimiteTermico(IGuardrail):
    """Nenhum alimentador pode passar de 90% da capacidade nominal."""

    def __init__(self, limite: float = 0.90):
        self._limite = limite

    def validar(self, plano, estados) -> Optional[str]:
        for alim, carga in plano.carga_resultante_mw.items():
            cap = estados[alim].capacidade_mw
            if carga > cap * self._limite:
                return f"{alim}: {carga:.1f} MW > {self._limite:.0%} de {cap:.1f} MW"
        return None


class GuardrailTensao(IGuardrail):
    """Tensão estimada deve ficar >= 0,93 pu (faixa adequada do PRODIST).

    Estimativa simplificada: cada 10% de carga extra derruba 0,01 pu.
    """

    def __init__(self, minimo_pu: float = 0.93):
        self._min = minimo_pu

    def validar(self, plano, estados) -> Optional[str]:
        for m in plano.manobras:
            dest = estados[m.destino]
            queda = 0.1 * (m.carga_mw / dest.capacidade_mw)
            if dest.tensao_pu - queda < self._min:
                return f"{m.destino}: tensão estimada {dest.tensao_pu - queda:.3f} pu"
        return None


class GuardrailCargaPrioritaria(IGuardrail):
    """Carga essencial afetada sem destino exige decisão humana."""

    def validar(self, plano, estados) -> Optional[str]:
        orfaos = [a for a in getattr(plano, "sem_destino", []) if estados[a].prioritario]
        return f"carga prioritária sem destino: {orfaos}" if orfaos else None


class GuardrailTaxaManobras(IGuardrail):
    """No máximo N manobras automáticas por ciclo (evita efeito cascata)."""

    def __init__(self, maximo: int = 5):
        self._max = maximo

    def validar(self, plano, estados) -> Optional[str]:
        n = len(plano.manobras)
        return f"{n} manobras > limite de {self._max}" if n > self._max else None


# ---------------------------------------------------------------- E
class ExecutorManobras:
    def __init__(self, atuador: IAtuadorRede, guardrails: list):
        self._atuador = atuador
        self._guardrails: list[IGuardrail] = guardrails

    def executar(self, plano: PlanoRedistribuicao, estados: dict) -> dict:
        violacoes = [v for g in self._guardrails if (v := g.validar(plano, estados))]
        if not plano.manobras:
            # nada a manobrar; se há carga sem destino, o operador decide
            status = "PENDENTE_APROVACAO" if plano.sem_destino else "SEM_ACAO"
        elif violacoes:
            status = "PENDENTE_APROVACAO"  # humano no circuito
        else:
            self._atuador.aplicar(plano)
            status = "EXECUTADO"
        return {"status": status, "violacoes": violacoes,
                "manobras": [m.__dict__ for m in plano.manobras],
                "sem_destino": plano.sem_destino}


# ------------------------------------------------------ Orquestrador
class CicloMapeK(ICicloMapeK):
    def __init__(self, monitor: MonitorRede, analisador: AnalisadorRede,
                 planejador: PlanejadorRedistribuicao, executor: ExecutorManobras,
                 publicador: IPublicadorDecisoes,
                 explicador: Optional[IExplicadorDecisao] = None):
        self._m, self._a, self._p, self._e = monitor, analisador, planejador, executor
        self._publicador = publicador
        self._explicador = explicador

    def executar_ciclo(self, subestacao_id: str) -> dict:
        estados = self._m.coletar(subestacao_id)
        diag = self._a.analisar(estados)
        plano = self._p.planejar(diag, estados)
        decisao = self._e.executar(plano, estados)
        decisao.update(subestacao_id=subestacao_id,
                       instante=datetime.now(timezone.utc).isoformat())
        if self._explicador and decisao["status"] != "SEM_ACAO":
            try:
                decisao["explicacao"] = self._explicador.explicar(decisao)
            except Exception:
                decisao["explicacao"] = "Explicação indisponível; ver violações e manobras."
        self._publicador.publicar(decisao)  # toda decisão vai para a auditoria
        return decisao
