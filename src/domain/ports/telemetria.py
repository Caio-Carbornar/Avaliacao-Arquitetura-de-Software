"""Contratos de telemetria (ADRs 003 e 004). Somente abstrações: A = 1."""
from abc import ABC, abstractmethod
from datetime import datetime


class ITelemetryReading(ABC):
    """Leitura de um medidor, já em kWh e UTC (glossário: Leitura).

    Contrato de dados: classe abstrata (não instanciável diretamente) cujas
    implementações concretas são dataclasses na Application ou na Infrastructure.
    """

    tenant_id: str
    device_id: str
    timestamp: datetime
    value: float


class IConsumoAgregado(ABC):
    """Consumo agregado de um medidor ou região numa janela de tempo.

    Contrato de dados: classe abstrata (não instanciável diretamente) cujas
    implementações concretas são dataclasses na Application ou na Infrastructure.
    """

    media_kwh: float
    pico_kwh: float
    instante_pico: datetime


class ITelemetryPublisher(ABC):
    """Porta de saída da Ingestão: isola o Kafka (ADR 003)."""

    @abstractmethod
    def publish(self, reading: ITelemetryReading) -> None: ...


class ITelemetryQueryRepository(ABC):
    """Porta de leitura da Consulta: isola o TimescaleDB (ADR 003)."""

    @abstractmethod
    def obter_consumo_agregado(self, tenant_id: str, device_id: str,
                               inicio: datetime, fim: datetime) -> IConsumoAgregado: ...
