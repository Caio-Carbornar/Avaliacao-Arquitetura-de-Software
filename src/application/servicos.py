"""Serviços de Ingestão e Consulta (ADRs 003, 004, 006 e 008). A = 0."""
from dataclasses import dataclass
from datetime import datetime

from domain.ports.alerta import IAlertaPicoStrategy
from domain.ports.protocolos import DecoderFactory
from domain.ports.servicos import IConsultaService, IIngestaoService
from domain.ports.telemetria import (ITelemetryPublisher, ITelemetryQueryRepository,
                                     ITelemetryReading)


@dataclass(frozen=True)
class TelemetryReading(ITelemetryReading):
    tenant_id: str
    device_id: str  # já pseudonimizado na borda
    timestamp: datetime
    value: float


class IngestaoService(IIngestaoService):
    """Decodifica pelo Factory Method do tenant, valida e publica (DIP)."""

    def __init__(self, fabricas: dict, publisher: ITelemetryPublisher):
        self._fabricas: dict[str, DecoderFactory] = fabricas
        self._publisher = publisher

    def processar_leitura(self, tenant_id: str, payload: bytes) -> None:
        leitura: ITelemetryReading = self._fabricas[tenant_id].decodificar(payload)
        if leitura.value is None or leitura.value < 0:
            raise ValueError("Leitura de telemetria inválida")
        self._publisher.publish(TelemetryReading(
            leitura.tenant_id, leitura.device_id, leitura.timestamp, leitura.value))


class ConsultaService(IConsultaService):
    """Contexto do Strategy: delega a regra de alerta (ADR 008)."""

    def __init__(self, repository: ITelemetryQueryRepository,
                 estrategias: dict, padrao: IAlertaPicoStrategy):
        self._repository = repository
        self._estrategias: dict[str, IAlertaPicoStrategy] = estrategias
        self._padrao = padrao

    def resumo_para_dashboard(self, tenant_id, device_id, inicio, fim) -> dict:
        ag = self._repository.obter_consumo_agregado(tenant_id, device_id, inicio, fim)
        estrategia = self._estrategias.get(tenant_id, self._padrao)
        return {"media_kwh": round(ag.media_kwh, 2),
                "pico_kwh": round(ag.pico_kwh, 2),
                "alerta_pico": estrategia.avaliar(ag)}
