"""Interfaces dos serviços de aplicação (ADR 004)."""
from abc import ABC, abstractmethod
from datetime import datetime


class IIngestaoService(ABC):
    @abstractmethod
    def processar_leitura(self, tenant_id: str, payload: bytes) -> None: ...


class IConsultaService(ABC):
    @abstractmethod
    def resumo_para_dashboard(self, tenant_id: str, device_id: str,
                              inicio: datetime, fim: datetime) -> dict: ...
