from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pairs_ibra.data.loaders import (
    b3_sessions,
    build_dataset,
    expand_composition,
    load_dataset,
    normalize_ticker,
    read_bloomberg_wide,
    read_composition,
    read_sectors,
    save_dataset,
)
from pairs_ibra.data.synthetic import SyntheticData

BBG = """Dates,Petr4 BZ Equity,Vale3 BZ Equity,Itub4 BZ Equity,
02/01/2008,10.5,#N/A,30.1,
03/01/2008,10.7,50.0,#N/A,
04/01/2008,#N/A,#N/A,#N/A,
"""


def test_normalize_ticker() -> None:
    assert normalize_ticker("Petr4 BZ Equity") == "PETR4"
    assert normalize_ticker("  vale3 bz ") == "VALE3"
    assert normalize_ticker("TAEE11") == "TAEE11"


def test_read_bloomberg_wide(tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_text(BBG)
    df = read_bloomberg_wide(p)
    assert list(df.columns) == ["PETR4", "VALE3", "ITUB4"]
    assert df.index[0] == pd.Timestamp("2008-01-02")
    assert df.loc["2008-01-03", "PETR4"] == pytest.approx(10.7)
    assert np.isnan(df.loc["2008-01-02", "VALE3"])
    assert df.loc["2008-01-04"].isna().all()


def test_duplicate_tickers_after_normalization_raise(tmp_path: Path) -> None:
    p = tmp_path / "x.txt"
    p.write_text("Dates,Petr4 BZ Equity,PETR4 BZ Equity\n02/01/2008,1,2\n")
    with pytest.raises(ValueError, match="duplicados"):
        read_bloomberg_wide(p)


def test_b3_sessions_skip_holidays() -> None:
    s = b3_sessions(pd.Timestamp("2008-01-02"), pd.Timestamp("2008-12-31"))
    assert pd.Timestamp("2008-02-04") not in s   # carnaval
    assert pd.Timestamp("2008-04-21") not in s   # Tiradentes
    assert pd.Timestamp("2008-01-03") in s


def test_read_composition_and_expand(tmp_path: Path) -> None:
    p = tmp_path / "c.txt"
    p.write_text("data;ticker;peso\n02/01/2008;PETR4 BZ;60\n02/01/2008;VALE3 BZ;40\n"
                 "02/05/2008;VALE3 BZ;100\n")
    comp = read_composition(p)
    assert comp["weight"].sum() == pytest.approx(2.0)  # % convertido em fração
    sessions = b3_sessions(pd.Timestamp("2008-01-02"), pd.Timestamp("2008-06-30"))
    w = expand_composition(comp, sessions, pd.Index(["PETR4", "VALE3", "ITUB4"]))
    assert w.loc["2008-04-30", "PETR4"] and not w.loc["2008-05-02", "PETR4"]
    assert w.loc["2008-06-30", "VALE3"]
    assert not w["ITUB4"].any()


def test_read_sectors_fills_missing(tmp_path: Path) -> None:
    book = read_sectors(None, pd.Index(["PETR3", "PETR4"]))
    assert (book.sectors["setor"] == "SEM_SETOR").all()
    assert list(book.sectors["emissor"]) == ["PETR", "PETR"]


def test_build_dataset_from_synthetic(dataset: object, synth: SyntheticData) -> None:
    from pairs_ibra.data.loaders import Dataset

    assert isinstance(dataset, Dataset)
    old, new = synth.duplicates[0]
    assert old not in dataset.tickers and new in dataset.tickers  # duplicada removida
    assert pd.Timestamp("2008-02-04") not in dataset.dates        # feriado removido
    # turnover = qtd × preço sem ajuste
    t = synth.planted[0].leg_a
    d = dataset.dates[100]
    assert dataset.turnover.loc[d, t] == pytest.approx(
        synth.volume.loc[d, t] * synth.close_raw.loc[d, t], rel=1e-5)
    # CDI diário derivado do índice acumulado
    assert dataset.market["cdi_daily"].iloc[5] == pytest.approx(1.10 ** (1 / 252) - 1, rel=1e-6)
    assert dataset.in_index.loc[dataset.dates[10], t]


def test_parquet_roundtrip(tmp_path: Path, dataset: object) -> None:
    from pairs_ibra.data.loaders import Dataset

    assert isinstance(dataset, Dataset)
    save_dataset(dataset, tmp_path)
    back = load_dataset(tmp_path)
    pd.testing.assert_frame_equal(back.close_adj, dataset.close_adj, check_freq=False,
                                  check_names=False)
    assert back.in_index.equals(dataset.in_index.astype(bool)) or \
        (back.in_index.to_numpy() == dataset.in_index.to_numpy()).all()


def test_liquidity_proxy_when_no_composition(synth_dir: Path) -> None:
    from pairs_ibra.config import config_from_dict
    from tests.conftest import synth_raw

    raw = synth_raw(synth_dir)
    raw["universe"]["source"] = "liquidity_proxy"
    raw["universe"]["proxy_top_n"] = 20
    raw["data"]["files"]["ibra_composition"] = None
    ds, warnings = build_dataset(config_from_dict(raw), "/")
    counts = ds.in_index.sum(axis=1)
    assert counts.max() == 20
    assert any("proxy" in w for w in warnings)
