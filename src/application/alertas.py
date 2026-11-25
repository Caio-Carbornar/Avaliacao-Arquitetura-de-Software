"""Estratégias concretas de alerta de pico (ADR 008). A = 0."""
from domain.ports.alerta import IAlertaPicoStrategy
from domain.ports.telemetria import IConsumoAgregado


class AlertaPercentualStrategy(IAlertaPicoStrategy):
    def __init__(self, fator: float = 1.5):
        self._fator = fator

    def avaliar(self, agregado: IConsumoAgregado) -> bool:
        return agregado.pico_kwh > agregado.media_kwh * self._fator


class AlertaLimiteFixoStrategy(IAlertaPicoStrategy):
    def __init__(self, limite_kwh: float):
        self._limite = limite_kwh

    def avaliar(self, agregado: IConsumoAgregado) -> bool:
        return agregado.pico_kwh > self._limite


class AlertaHorarioPontaStrategy(IAlertaPicoStrategy):
    """Fator mais rígido entre 18h e 21h (horário de ponta)."""

    def __init__(self, fator_normal: float = 1.5, fator_ponta: float = 1.2):
        self._normal, self._ponta = fator_normal, fator_ponta

    def avaliar(self, agregado: IConsumoAgregado) -> bool:
        fator = self._ponta if 18 <= agregado.instante_pico.hour < 21 else self._normal
        return agregado.pico_kwh > agregado.media_kwh * fator
