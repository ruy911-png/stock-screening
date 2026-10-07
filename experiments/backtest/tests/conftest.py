import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def make_ohlcv(close, volume=1_000_000.0, spread=0.01):
    close = pd.Series(np.asarray(close, dtype=float), index=pd.bdate_range("2020-01-01", periods=len(close)))
    return pd.DataFrame({
        "Open": close,
        "High": close * (1 + spread),
        "Low": close * (1 - spread),
        "Close": close,
        "Volume": volume,
    })


@pytest.fixture
def ohlcv():
    return make_ohlcv
