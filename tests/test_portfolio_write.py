"""Gravação na carteira: formato preservado, soma com preço médio, backup e segurança."""

import os
from datetime import datetime

import pytest

from app.connectors import portfolio_write
from app.connectors.investments import PortfolioFileError, read_portfolio
from app.models import AssetDraft

NOW = datetime(2026, 9, 29, 10, 0)


def draft(ticker="MXRF11", asset_type="FII", quantity=10, price=9.8):
    return AssetDraft(ticker=ticker, asset_type=asset_type, quantity=quantity, price=price)


@pytest.fixture
def csv_file(tmp_path):
    return tmp_path / "carteira.csv"


def test_excel_ptbr_format_is_preserved(csv_file, tmp_path):
    original = "Ticker;Tipo;Quantidade;Preço médio;Corretora\r\nMXRF11;FII;10;10,20;XP\r\nPETR4;Ação;1.000;30,5;Rico\r\n"
    csv_file.write_bytes(original.encode("cp1252"))

    plan = portfolio_write.add_holding(csv_file, draft(), tmp_path / "backups", NOW)

    assert plan.exists and plan.new_quantity == 20
    text = csv_file.read_bytes().decode("cp1252")
    # Mesmo separador, vírgula decimal, quebras de linha e colunas extras intactas
    assert text == "Ticker;Tipo;Quantidade;Preço médio;Corretora\r\nMXRF11;FII;20;10;XP\r\nPETR4;Ação;1.000;30,5;Rico\r\n"
    assert {h.ticker: h.quantity for h in read_portfolio(csv_file)} == {"MXRF11": 20, "PETR4": 1000}


def test_new_asset_is_appended(csv_file, tmp_path):
    csv_file.write_text("ticker,tipo,quantidade,preco_medio\nPETR4,ação,5,30\n\n", encoding="utf-8")

    plan = portfolio_write.add_holding(csv_file, draft(quantity=3, price=9.87), tmp_path / "b", NOW)

    assert not plan.exists
    assert csv_file.read_text(encoding="utf-8") == \
        "ticker,tipo,quantidade,preco_medio\nPETR4,ação,5,30\nMXRF11,FII,3,9.87\n"


def test_duplicate_rows_become_one(csv_file, tmp_path):
    csv_file.write_text("ticker,tipo,quantidade,preco_medio\nMXRF11,FII,10,10\nPETR4,ação,5,30\nmxrf11,fii,10,12\n",
                        encoding="utf-8")

    plan = portfolio_write.add_holding(csv_file, draft(quantity=20, price=8), tmp_path / "b", NOW)

    assert plan.current.quantity == 20 and plan.current.avg_price == 11
    assert plan.new_quantity == 40 and plan.new_avg_price == pytest.approx(9.5)
    assert csv_file.read_text(encoding="utf-8") == "ticker,tipo,quantidade,preco_medio\nMXRF11,FII,40,9.5\nPETR4,ação,5,30\n"


def test_bom_is_kept(csv_file, tmp_path):
    csv_file.write_bytes("ticker,tipo,quantidade,preco_medio\nPETR4,ação,5,30\n".encode("utf-8-sig"))
    portfolio_write.add_holding(csv_file, draft(), tmp_path / "b", NOW)
    assert csv_file.read_bytes().startswith(b"\xef\xbb\xbf")


def test_invalid_file_is_not_touched(csv_file, tmp_path):
    original = "ticker,tipo,quantidade,preco_medio\nPETR4,ação,-5,30\n"
    csv_file.write_text(original, encoding="utf-8")

    with pytest.raises(PortfolioFileError, match="Linha 2"):
        portfolio_write.add_holding(csv_file, draft(), tmp_path / "b", NOW)

    assert csv_file.read_text(encoding="utf-8") == original
    assert not (tmp_path / "b").exists()


def test_file_open_in_excel(csv_file, tmp_path, monkeypatch):
    original = "ticker,tipo,quantidade,preco_medio\nPETR4,ação,5,30\n"
    csv_file.write_text(original, encoding="utf-8")

    def locked(src, dst):
        raise PermissionError("arquivo em uso")

    monkeypatch.setattr(os, "replace", locked)
    with pytest.raises(PortfolioFileError, match="aberta em outro programa"):
        portfolio_write.add_holding(csv_file, draft(), tmp_path / "b", NOW)

    assert csv_file.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob("*.tmp"))


def test_backups_are_kept_and_pruned(csv_file, tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_write, "KEEP_BACKUPS", 3)
    csv_file.write_text("ticker,tipo,quantidade,preco_medio\n", encoding="utf-8")
    backups = tmp_path / "b"

    for i in range(5):
        portfolio_write.add_holding(csv_file, draft(quantity=1), backups, NOW.replace(second=i))

    kept = sorted(p.name for p in backups.iterdir())
    assert len(kept) == 3
    assert kept[-1].startswith("carteira-20260929-100004")
    assert read_portfolio(csv_file)[0].quantity == 5


def test_draft_uses_the_same_rules_as_the_file():
    assert portfolio_write.draft_from(" hglg11 ", "fiis", 1, 150) == draft("HGLG11", "FII", 1, 150)
    assert portfolio_write.draft_from("Tesouro  Selic 2031", "tesouro", 0.5, 15000).ticker == "Tesouro Selic 2031"
    with pytest.raises(PortfolioFileError):
        portfolio_write.draft_from("VOO", "ação", 1, 1)  # VOO não é ticker da B3
    with pytest.raises(PortfolioFileError):
        portfolio_write.draft_from("MXRF11", "FII", float("nan"), 1)
