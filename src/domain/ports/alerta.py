"""Strategy da regra de alerta de pico (ADR 008)."""
from abc import ABC, abstractmethod

from domain.ports.telemetria import IConsumoAgregado


class IAlertaPicoStrategy(ABC):
    @abstractmethod
    def avaliar(self, agregado: IConsumoAgregado) -> bool: ...
