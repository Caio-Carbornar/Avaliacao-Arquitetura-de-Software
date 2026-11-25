"""Factory Method (ADR 006) e alvo do Adapter (ADR 007)."""
from abc import ABC, abstractmethod

from domain.ports.telemetria import ITelemetryReading


class ITelemetryDecoder(ABC):
    """Interface alvo do Adapter: converte o payload bruto de um fornecedor."""

    @abstractmethod
    def converter(self, payload: bytes) -> ITelemetryReading: ...


class DecoderFactory(ABC):
    """Criador abstrato do Factory Method.

    Tem uma operação concreta (decodificar), mas continua abstrato porque o
    Factory Method criar_decoder() é abstrato; por isso conta como abstração.
    """

    @abstractmethod
    def criar_decoder(self) -> ITelemetryDecoder: ...

    def decodificar(self, payload: bytes) -> ITelemetryReading:
        return self.criar_decoder().converter(payload)
