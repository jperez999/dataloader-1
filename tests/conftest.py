#
# Copyright (c) 2021, NVIDIA CORPORATION.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import random

import dask
import numpy as np
import pandas as pd

try:
    import cudf

    try:
        import cudf.testing._utils

        assert_eq = cudf.testing._utils.assert_eq
    except ImportError:
        import cudf.tests.utils

        assert_eq = cudf.tests.utils.assert_eq
except ImportError:
    cudf = None

    def assert_eq(a, b, *args, **kwargs):
        if isinstance(a, pd.DataFrame):
            return pd.testing.assert_frame_equal(a, b, *args, **kwargs)
        elif isinstance(a, pd.Series):
            return pd.testing.assert_series_equal(a, b, *args, **kwargs)
        else:
            return np.testing.assert_allclose(a, b)


import pytest

from merlin.core.dispatch import make_df
from merlin.io import Dataset
from merlin.schema import Tags


@pytest.fixture(scope="session")
def df():
    df = (
        dask.datasets.timeseries(
            start="2000-01-01",
            end="2000-01-04",
            freq="60s",
            dtypes={
                "name-cat": str,
                "name-string": str,
                "id": int,
                "label": int,
                "x": float,
                "y": float,
                "z": float,
            },
        )
        .reset_index()
        .compute()
    )

    # convert to a categorical
    df["name-string"] = df["name-string"].astype("category").cat.codes.astype("int32")
    df["name-cat"] = df["name-cat"].astype("category").cat.codes.astype("int32")

    # Add two random null values to each column
    imax = len(df) - 1
    for col in df.columns:
        if col in ["name-cat", "label", "id"]:
            break
        for _ in range(2):
            rand_idx = random.randint(1, imax - 1)
            if rand_idx == df[col].shape[0] // 2:
                # dont want null in median
                rand_idx += 1
            df[col].iloc[rand_idx] = None

    df = df.drop("timestamp", axis=1)
    return df


@pytest.fixture(scope="session")
def parquet_path(df, tmpdir_factory):
    # we're writing out to parquet independently of the dataset here
    # since the serialization is relatively expensive, and we can do at the 'session'
    # scope - but the dataset fixture needs to be at the 'function' scope so that
    # we can set options like 'part_mem_fraction' and 'cpu'
    datadir = tmpdir_factory.mktemp("test_dataset")
    half = int(len(df) // 2)

    # Write Parquet Dataset
    df.iloc[:half].to_parquet(str(datadir / "dataset-0.parquet"), chunk_size=1000)
    df.iloc[half:].to_parquet(str(datadir / "dataset-1.parquet"), chunk_size=1000)
    return datadir


@pytest.fixture(scope="function")
def dataset(request, tmpdir_factory, parquet_path):
    try:
        gpu_memory_frac = request.getfixturevalue("gpu_memory_frac")
    except Exception:  # pylint: disable=broad-except
        gpu_memory_frac = 0.01

    try:
        cpu = request.getfixturevalue("cpu")
    except Exception:  # pylint: disable=broad-except
        cpu = False

    dataset = Dataset(parquet_path, engine="parquet", part_mem_fraction=gpu_memory_frac, cpu=cpu)
    dataset.schema["label"] = dataset.schema["label"].with_tags(Tags.TARGET)
    return dataset


# Allow to pass devices as parameters
def pytest_addoption(parser):
    parser.addoption("--devices", action="store", default="0", help="0,1,..,n-1")
    parser.addoption("--report", action="store", default="1", help="0 | 1")


@pytest.fixture
def devices(request):
    return request.config.getoption("--devices")


@pytest.fixture
def report(request):
    return request.config.getoption("--report")


@pytest.fixture
def multihot_data():
    return {
        "Authors": [[0], [0, 5], [1, 2], [2]],
        "Reviewers": [[0], [0, 5], [1, 2], [2]],
        "Engaging User": [1, 1, 0, 4],
        "Embedding": [
            [0.1, 0.2, 0.3],
            [0.3, 0.4, 0.5],
            [0.6, 0.7, 0.8],
            [0.8, 0.4, 0.2],
        ],
        "Post": [1, 2, 3, 4],
    }


@pytest.fixture
def multihot_dataset(multihot_data):
    ds = Dataset(make_df(multihot_data))
    ds.schema["Post"] = ds.schema["Post"].with_tags(Tags.TARGET)
    return ds
