"""Infrastructure.Persistence: TimescaleDB, exclusivo da Consulta (ADR 005). A = 0."""
from dataclasses import dataclass
from datetime import datetime

import psycopg2  # driver do fornecedor: só aqui

from domain.ports.telemetria import IConsumoAgregado, ITelemetryQueryRepository


@dataclass(frozen=True)
class ConsumoAgregadoTimescale(IConsumoAgregado):
    media_kwh: float
    pico_kwh: float
    instante_pico: datetime


class TimescaleTelemetryRepository(ITelemetryQueryRepository):
    SQL = """
        SELECT AVG(value_kwh), MAX(value_kwh),
               (array_agg(ts ORDER BY value_kwh DESC))[1]
        FROM telemetria
        WHERE tenant_id = %s AND device_id = %s AND ts BETWEEN %s AND %s
    """

    def __init__(self, conexao: "psycopg2.extensions.connection"):
        self._conexao = conexao

    def obter_consumo_agregado(self, tenant_id, device_id, inicio, fim):
        with self._conexao.cursor() as cur:
            cur.execute(self.SQL, (tenant_id, device_id, inicio, fim))
            media, pico, instante = cur.fetchone()
        return ConsumoAgregadoTimescale(media, pico, instante)
