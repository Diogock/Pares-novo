from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pairs_ibra.config import Config, config_from_dict, load_raw
from pairs_ibra.data import synthetic
from pairs_ibra.data.loaders import Dataset, build_dataset

ROOT = Path(__file__).resolve().parents[1]


def base_raw() -> dict[str, Any]:
    return load_raw(ROOT / "configs" / "base.yaml")


def make_cfg(**overrides: dict[str, Any]) -> Config:
    raw = base_raw()
    for section, values in overrides.items():
        raw[section] = {**raw[section], **values}
    return config_from_dict(raw)


@pytest.fixture(scope="session")
def synth() -> synthetic.SyntheticData:
    return synthetic.generate()


@pytest.fixture(scope="session")
def synth_dir(tmp_path_factory: pytest.TempPathFactory, synth: synthetic.SyntheticData) -> Path:
    d = tmp_path_factory.mktemp("synth")
    synthetic.write_all(synth, d / "raw", d / "sectors.xlsx")
    return d


def synth_raw(synth_dir: Path) -> dict[str, Any]:
    raw = base_raw()
    raw["data"]["raw_dir"] = str(synth_dir / "raw")
    raw["data"]["files"]["sectors"] = str(synth_dir / "sectors.xlsx")
    return raw


@pytest.fixture(scope="session")
def synth_cfg(synth_dir: Path) -> Config:
    return config_from_dict(synth_raw(synth_dir))


@pytest.fixture(scope="session")
def dataset(synth_cfg: Config) -> Dataset:
    ds, _ = build_dataset(synth_cfg, "/")
    return ds
