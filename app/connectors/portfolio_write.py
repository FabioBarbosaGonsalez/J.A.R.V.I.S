"""Inserir um ativo na carteira (só depois do clique em Confirmar, na aba privada).

- Antes de qualquer alteração, uma cópia do arquivo vai para `data/backups/`.
- O arquivo é regravado no mesmo formato em que estava (separador, vírgula
  decimal do Excel em português, codificação e quebras de linha). As outras
  linhas e colunas ficam como estavam.
- Se o ativo já existe, a quantidade é somada e o preço médio recalculado
  (média ponderada). Linhas repetidas do mesmo ativo viram uma só.
- A gravação é atômica: escreve num arquivo temporário e troca de uma vez,
  então o arquivo nunca fica pela metade.

As mensagens daqui aparecem na interface: nada de nomes de arquivo.
"""

import csv
import io
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.connectors import investments
from app.connectors.investments import Holding, PortfolioFileError
from app.formatting import normalize
from app.models import AssetDraft

HEADER = ["ticker", "tipo", "quantidade", "preco_medio"]
KEEP_BACKUPS = 30


@dataclass
class AddPlan:
    """O que muda na carteira ao inserir o ativo."""

    draft: AssetDraft
    current: Holding | None
    new_quantity: float
    new_avg_price: float

    @property
    def exists(self) -> bool:
        return self.current is not None


def draft_from(raw_ticker: str | None, raw_type: str | None, quantity: float, price: float) -> AssetDraft:
    """Valida como na leitura do CSV. Erros sobem como `PortfolioFileError`."""
    ticker, asset_type = investments.validate_asset(raw_ticker, raw_type)
    investments.validate_amounts(quantity, price)
    return AssetDraft(ticker=ticker, asset_type=asset_type, quantity=quantity, price=price)


def plan_add(holdings: list[Holding], draft: AssetDraft) -> AddPlan:
    current = next((h for h in holdings if h.ticker == draft.ticker), None)
    if current is None:
        return AddPlan(draft, None, draft.quantity, draft.price)
    if current.asset_type != draft.asset_type:
        raise PortfolioFileError(
            f"{draft.ticker} já está na carteira como {current.asset_type}, e não como {draft.asset_type}."
        )
    total = current.quantity + draft.quantity
    avg = (current.avg_price * current.quantity + draft.price * draft.quantity) / total
    return AddPlan(draft, current, total, avg)


def _format_number(value: float, excel_ptbr: bool, decimals: int) -> str:
    text = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return text.replace(".", ",") if excel_ptbr else text


def _column(fieldnames: list[str], name: str) -> int:
    normalized = [normalize(f).strip().replace(" ", "_") for f in fieldnames]
    return normalized.index(name)


def rewrite(text: str, plan: AddPlan) -> str:
    """Novo conteúdo do CSV com o ativo inserido ou somado. Não mexe nas outras linhas."""
    excel_ptbr = investments.is_excel_ptbr(text)
    delimiter = ";" if excel_ptbr else ","
    newline = "\r\n" if "\r\n" in text else "\n"
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter)) or [HEADER]
    header = rows[0]
    col = {name: _column(header, name) for name in HEADER}

    quantity = _format_number(plan.new_quantity, excel_ptbr, 8)
    avg_price = _format_number(plan.new_avg_price, excel_ptbr, 6)
    out = [header]
    placed = False
    for line_no, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            out.append(row)
            continue
        cells = row + [""] * (len(header) - len(row))
        holding = investments._parse_row(dict(zip(HEADER, (cells[col[n]] for n in HEADER))), line_no, excel_ptbr)
        if holding.ticker != plan.draft.ticker:
            out.append(row)
        elif not placed:
            # Primeira linha do ativo recebe o total; as repetidas já entraram na soma
            cells[col["quantidade"]] = quantity
            cells[col["preco_medio"]] = avg_price
            out.append(cells)
            placed = True
    if not placed:
        new_row = [""] * len(header)
        new_row[col["ticker"]] = plan.draft.ticker
        new_row[col["tipo"]] = plan.draft.asset_type
        new_row[col["quantidade"]] = quantity
        new_row[col["preco_medio"]] = avg_price
        # Tira linhas em branco do fim para a nova não ficar separada
        while len(out) > 1 and not any(cell.strip() for cell in out[-1]):
            out.pop()
        out.append(new_row)

    buffer = io.StringIO()
    csv.writer(buffer, delimiter=delimiter, lineterminator=newline).writerows(out)
    return buffer.getvalue()


def _backup(path: Path, backup_dir: Path, now: datetime) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_dir / f"{path.stem}-{now:%Y%m%d-%H%M%S-%f}{path.suffix}")
    backups = sorted(backup_dir.glob(f"{path.stem}-*{path.suffix}"))
    for old in backups[:-KEEP_BACKUPS]:
        old.unlink(missing_ok=True)


def add_holding(path: Path, draft: AssetDraft, backup_dir: Path, now: datetime) -> AddPlan:
    """Grava o ativo na carteira. Erros sobem como `PortfolioFileError`, sem alterar nada."""
    with investments._lock:
        if path.exists():
            text, encoding = investments.decode_portfolio(path.read_bytes())
            holdings = investments.parse_portfolio(text)  # só grava se o arquivo inteiro for válido
        else:
            text, encoding, holdings = ",".join(HEADER) + "\n", "utf-8", []

        plan = plan_add(holdings, draft)
        content = rewrite(text, plan)
        try:
            encoded = content.encode(encoding)
        except UnicodeEncodeError:
            encoded = content.encode("utf-8-sig")

        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        try:
            if path.exists():
                _backup(path, backup_dir, now)
            temp.write_bytes(encoded)
            os.replace(temp, path)
        except PermissionError:
            temp.unlink(missing_ok=True)
            raise PortfolioFileError(
                "A planilha da carteira está aberta em outro programa. Feche-a e confirme de novo."
            ) from None
        except OSError:
            temp.unlink(missing_ok=True)
            raise PortfolioFileError("Não foi possível gravar a carteira.") from None
        return plan
