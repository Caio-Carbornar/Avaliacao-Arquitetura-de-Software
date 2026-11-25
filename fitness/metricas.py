"""Fitness function: métricas de Robert C. Martin calculadas a partir do código.

Lê o código de src/ com o módulo ast (sem executar nada), descobre as classes de
cada pacote e as dependências entre elas, e calcula para cada pacote:

    Ca = classes de FORA que dependem de classes do pacote
    Ce = classes do pacote que dependem de classes de FORA
    I  = Ce / (Ca + Ce)            (instabilidade)
    A  = Na / Nc                   (abstracionalidade)
    D  = |A + I - 1|               (distância da sequência principal)

Também verifica as regras de dependência entre camadas. Gera um relatório em
Markdown e um gráfico SVG da sequência principal. Termina com código 1 se
alguma regra for violada, o que faz o build do CI falhar.

Uso:  python fitness/metricas.py [--relatorio docs/relatorio-metricas.md]
"""
import argparse
import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SRC = RAIZ / "src"
LIMITE_D = 0.1
BIBLIOTECAS_FORNECEDOR = {"confluent_kafka", "psycopg2", "boto3", "onnxruntime",
                          "requests", "jsonschema"}


@dataclass
class Classe:
    nome: str
    pacote: str
    abstrata: bool
    bases: list
    usa: set = field(default_factory=set)   # nomes de classes internas usadas


@dataclass
class Metricas:
    pacote: str
    nc: int
    na: int
    ca: int
    ce: int

    @property
    def a(self) -> float:
        return self.na / self.nc if self.nc else 0.0

    @property
    def i(self) -> float:
        return self.ce / (self.ca + self.ce) if (self.ca + self.ce) else 0.0

    @property
    def d(self) -> float:
        return abs(self.a + self.i - 1)


def pacote_do_modulo(caminho: Path) -> str:
    partes = caminho.relative_to(SRC).parts
    if partes[0] == "domain":
        return "Domain.Ports"
    if partes[0] == "application":
        return "Application"
    return "Infrastructure." + partes[1].capitalize()


def pacote_do_import(modulo: str) -> str | None:
    """Converte 'infrastructure.messaging.kafka' em 'Infrastructure.Messaging'."""
    partes = modulo.split(".")
    if partes[0] == "domain":
        return "Domain.Ports"
    if partes[0] == "application":
        return "Application"
    if partes[0] == "infrastructure" and len(partes) > 1:
        return "Infrastructure." + partes[1].capitalize()
    return None


def eh_abstrata(no: ast.ClassDef) -> bool:
    if any(isinstance(b, ast.Name) and b.id == "ABC" for b in no.bases):
        return True
    for item in ast.walk(no):
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in item.decorator_list:
                if isinstance(dec, ast.Name) and dec.id == "abstractmethod":
                    return True
    return False


def analisar_codigo() -> tuple[dict, list]:
    """Devolve as classes encontradas e a lista de imports (modulo, pacote, importado)."""
    classes: dict[str, Classe] = {}
    imports = []
    arvores = []
    for arquivo in sorted(SRC.rglob("*.py")):
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        pacote = pacote_do_modulo(arquivo)
        arvores.append((arquivo, pacote, arvore))
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                for alias in no.names:
                    imports.append((arquivo, pacote, alias.name))
            elif isinstance(no, ast.ImportFrom) and no.module:
                imports.append((arquivo, pacote, no.module))
        for no in arvore.body:
            if isinstance(no, ast.ClassDef):
                bases = [b.id for b in no.bases if isinstance(b, ast.Name)]
                classes[no.name] = Classe(no.name, pacote, eh_abstrata(no), bases)

    # Dependências: qualquer nome de classe interna citado no corpo da classe
    for arquivo, pacote, arvore in arvores:
        for no in arvore.body:
            if isinstance(no, ast.ClassDef):
                for item in ast.walk(no):
                    if isinstance(item, ast.Name) and item.id in classes \
                            and item.id != no.name:
                        classes[no.name].usa.add(item.id)
    return classes, imports


def calcular(classes: dict) -> list[Metricas]:
    pacotes = sorted({c.pacote for c in classes.values()},
                     key=lambda p: (p != "Domain.Ports", p != "Application", p))
    resultado = []
    for p in pacotes:
        de_dentro = [c for c in classes.values() if c.pacote == p]
        de_fora = [c for c in classes.values() if c.pacote != p]
        ca = sum(1 for c in de_fora if any(classes[u].pacote == p for u in c.usa))
        ce = sum(1 for c in de_dentro if any(classes[u].pacote != p for u in c.usa))
        resultado.append(Metricas(p, len(de_dentro),
                                  sum(c.abstrata for c in de_dentro), ca, ce))
    return resultado


def verificar_regras(classes: dict, imports: list, metricas: list) -> list[tuple]:
    """Cada regra devolve (nome, passou, detalhe)."""
    regras = []

    viol = [f"{a.name} importa {m}" for a, p, m in imports
            if p == "Domain.Ports" and (pacote_do_import(m) or "Domain.Ports") != "Domain.Ports"]
    regras.append(("R1. Domain.Ports não referencia Application nem Infrastructure",
                   not viol, viol))

    viol = [f"{a.name} importa {m}" for a, p, m in imports
            if p == "Application" and (pacote_do_import(m) or "").startswith("Infrastructure")]
    regras.append(("R2. Application não referencia Infrastructure", not viol, viol))

    viol = [f"{a.name} importa {m}" for a, p, m in imports
            if m.split(".")[0] in BIBLIOTECAS_FORNECEDOR and not p.startswith("Infrastructure")]
    regras.append(("R3. Bibliotecas de fornecedor só na Infrastructure", not viol, viol))

    viol = [c.nome for c in classes.values() if c.pacote.startswith("Infrastructure")
            and not any(classes.get(b) and classes[b].pacote == "Domain.Ports"
                        and classes[b].abstrata for b in c.bases)]
    regras.append(("R4. Toda classe de Infrastructure implementa uma abstração de "
                   "Domain.Ports", not viol, viol))

    viol = [c.nome for c in classes.values() if c.pacote == "Domain.Ports" and not c.abstrata]
    regras.append(("R5. Domain.Ports só contém abstrações (A = 1)", not viol, viol))

    viol = [f"{m.pacote}: D = {m.d:.2f}" for m in metricas if m.d > LIMITE_D]
    regras.append((f"R6. Todo pacote com D <= {LIMITE_D}", not viol, viol))
    return regras


def gerar_svg(metricas: list) -> str:
    """Gráfico I (x) por A (y) com a sequência principal A + I = 1."""
    w, h, m = 420, 420, 60
    px = lambda i: m + i * (w - 2 * m)
    py = lambda a: h - m - a * (h - 2 * m)
    pontos = {}
    for x in metricas:
        pontos.setdefault((round(x.i, 2), round(x.a, 2)), []).append(x.pacote)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w + 200}" height="{h}" '
           'font-family="Arial" font-size="12">',
           f'<rect width="{w + 200}" height="{h}" fill="white"/>',
           f'<polygon points="{px(0)},{py(0)} {px(0.3)},{py(0)} {px(0)},{py(0.3)}" fill="#f8d7da"/>',
           f'<polygon points="{px(1)},{py(1)} {px(0.7)},{py(1)} {px(1)},{py(0.7)}" fill="#f8d7da"/>',
           f'<text x="{px(0.02)}" y="{py(0.04)}">Zona de Dor</text>',
           f'<text x="{px(0.76)}" y="{py(0.96)}">Zona de Inutilidade</text>',
           f'<line x1="{px(0)}" y1="{py(1)}" x2="{px(1)}" y2="{py(0)}" stroke="#5B9BD4" '
           'stroke-width="2" stroke-dasharray="6,4"/>',
           f'<line x1="{px(0)}" y1="{py(0)}" x2="{px(1)}" y2="{py(0)}" stroke="#333"/>',
           f'<line x1="{px(0)}" y1="{py(0)}" x2="{px(0)}" y2="{py(1)}" stroke="#333"/>',
           f'<text x="{w / 2 - 60}" y="{h - 12}">Instabilidade (I)</text>',
           f'<text x="12" y="{h / 2}" transform="rotate(-90 12 {h / 2})">Abstracionalidade (A)</text>',
           f'<text x="{px(0) - 10}" y="{py(0) + 15}">0</text>',
           f'<text x="{px(1) - 4}" y="{py(0) + 15}">1</text>',
           f'<text x="{px(0) - 15}" y="{py(1) + 4}">1</text>']
    for (i, a), nomes in pontos.items():
        svg.append(f'<circle cx="{px(i)}" cy="{py(a)}" r="7" fill="#1A2D42"/>')
        for k, nome in enumerate(nomes):
            y = py(a) + 4 + k * 15 if a > 0.5 else py(a) + 4 - (len(nomes) - 1 - k) * 15
            svg.append(f'<text x="{px(i) + 12}" y="{y}">{nome}</text>')
    svg.append("</svg>")
    return "\n".join(svg)


def gerar_relatorio(metricas: list, regras: list) -> str:
    linhas = ["# Relatório automatizado de métricas de acoplamento", "",
              "Gerado por `fitness/metricas.py` a partir do código em `src/`. "
              "Não edite à mão: o CI regera este arquivo a cada *pull request*.", "",
              "| Pacote | Nc | Na | A | Ca | Ce | I | D |",
              "|---|---|---|---|---|---|---|---|"]
    for m in metricas:
        linhas.append(f"| {m.pacote} | {m.nc} | {m.na} | {m.a:.2f} | {m.ca} | {m.ce} "
                      f"| {m.i:.2f} | **{m.d:.2f}** |")
    linhas += ["", "![Sequência principal](img/sequencia-principal-automatica.svg)", "",
               "## Regras de arquitetura", "", "| Regra | Resultado |", "|---|---|"]
    for nome, ok, viol in regras:
        linhas.append(f"| {nome} | {'Aprovada' if ok else 'REPROVADA: ' + '; '.join(viol)} |")
    return "\n".join(linhas) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--relatorio", help="caminho do relatório Markdown a gerar")
    args = parser.parse_args()

    classes, imports = analisar_codigo()
    metricas = calcular(classes)
    regras = verificar_regras(classes, imports, metricas)

    print(f"{'Pacote':28} {'Nc':>3} {'Na':>3} {'A':>5} {'Ca':>3} {'Ce':>3} {'I':>5} {'D':>5}")
    for m in metricas:
        print(f"{m.pacote:28} {m.nc:>3} {m.na:>3} {m.a:>5.2f} {m.ca:>3} {m.ce:>3} "
              f"{m.i:>5.2f} {m.d:>5.2f}")
    print()
    for nome, ok, viol in regras:
        print(("[OK]    " if ok else "[FALHA] ") + nome + ("" if ok else f" -> {viol}"))

    if args.relatorio:
        destino = RAIZ / args.relatorio
        destino.write_text(gerar_relatorio(metricas, regras), encoding="utf-8")
        (destino.parent / "img").mkdir(exist_ok=True)
        (destino.parent / "img" / "sequencia-principal-automatica.svg").write_text(
            gerar_svg(metricas), encoding="utf-8")
        print(f"\nRelatório gerado em {args.relatorio}")

    return 0 if all(ok for _, ok, _ in regras) else 1


if __name__ == "__main__":
    sys.exit(main())
