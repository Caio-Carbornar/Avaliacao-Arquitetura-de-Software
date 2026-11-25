"""Portas do ciclo autônomo MAPE-K (ADR 013).

O contexto Autonomia da Rede trabalha só com dados agregados por alimentador.
Nenhuma porta recebe device_id: o MAPE-K nunca vê um medidor individual (LGPD).
"""
from abc import ABC, abstractmethod
from typing import Optional


class IEstadoAlimentador(ABC):
    """Estado de um alimentador (circuito que sai de uma subestação).

    Contrato de dados: classe abstrata (não instanciável diretamente) cujas
    implementações concretas são dataclasses na Application ou na Infrastructure.
    """

    alimentador_id: str
    subestacao_id: str
    energizado: bool
    carga_mw: float
    capacidade_mw: float
    tensao_pu: float
    prioritario: bool  # atende hospital, saneamento ou outra carga essencial


class IPlanoRedistribuicao(ABC):
    """Conjunto de manobras proposto pelo Planejador.

    Contrato de dados: classe abstrata (não instanciável diretamente) cujas
    implementações concretas são dataclasses na Application ou na Infrastructure.
    """

    manobras: list
    carga_resultante_mw: dict  # carga prevista em cada destino após as manobras
    sem_destino: list  # alimentadores afetados sem vizinho disponível


class IFonteEstadoRede(ABC):
    """M (Monitor): de onde vem o estado da rede."""

    @abstractmethod
    def estados(self, subestacao_id: str) -> list: ...


class IModeloPrevisaoCarga(ABC):
    """A (Analyze): modelo de IA que prevê a carga dos próximos 15 minutos."""

    @abstractmethod
    def prever_mw(self, estado: IEstadoAlimentador) -> float: ...


class IBaseConhecimento(ABC):
    """K (Knowledge): topologia, chaves de interligação e limites físicos."""

    @abstractmethod
    def vizinhos(self, alimentador_id: str) -> list:
        """Alimentadores que podem receber carga por uma chave de interligação."""


class IGuardrail(ABC):
    """Regra determinística de segurança física. Não usa IA."""

    @abstractmethod
    def validar(self, plano: IPlanoRedistribuicao, estados: dict) -> Optional[str]:
        """Devolve a violação encontrada ou None."""


class IAtuadorRede(ABC):
    """E (Execute): envia as manobras ao ADMS/SCADA da distribuidora."""

    @abstractmethod
    def aplicar(self, plano: IPlanoRedistribuicao) -> None: ...


class IPublicadorDecisoes(ABC):
    """Publica toda decisão no tópico autonomia.decisoes (auditoria imutável)."""

    @abstractmethod
    def publicar(self, decisao: dict) -> None: ...


class IExplicadorDecisao(ABC):
    """LLM que explica a decisão ao operador. Fica fora do caminho de decisão."""

    @abstractmethod
    def explicar(self, decisao: dict) -> str: ...


class ICicloMapeK(ABC):
    @abstractmethod
    def executar_ciclo(self, subestacao_id: str) -> dict: ...
