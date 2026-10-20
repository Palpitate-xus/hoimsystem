"""NumPy-only preprocessing checks; no torch import or actual clinical classifier needed."""

import pytest

from app.ai.ecg_network import normalize_input

np = pytest.importorskip("numpy")


def independent_population_normalization(values):
    """Explicit float32 arithmetic oracle, independent of ndarray.std implementation."""
    expected = np.empty((1, 12, 1000), dtype=np.float32)
    for lead in range(12):
        samples = np.asarray(values[lead], dtype=np.float32)
        mean = np.sum(samples, dtype=np.float32) / np.float32(1000)
        centered = samples - mean
        variance = np.sum(centered * centered, dtype=np.float32) / np.float32(1000)
        standard_deviation = np.sqrt(variance)
        denominator = max(standard_deviation, np.float32(1e-6))
        expected[0, lead] = centered / denominator
    return expected


def test_normalization_matches_population_std_oracle_and_preserves_lead_order():
    samples = np.arange(1000, dtype=np.float32)
    values = np.stack([(samples - 500) * (lead + 1) / 1000 + lead * 2 for lead in range(12)])
    # Unique shapes prevent an accidentally swapped/repeated lead from appearing valid.
    values[2] = np.sin(samples / 7)
    values[8] = np.cos(samples / 11)
    result = normalize_input(values)
    assert result.shape == (1, 12, 1000) and result.dtype == np.float32 and result.flags.c_contiguous
    np.testing.assert_array_equal(result, independent_population_normalization(values))
    np.testing.assert_allclose(result.mean(axis=-1), 0, atol=2e-6)
    np.testing.assert_allclose(result.std(axis=-1), 1, atol=2e-6)
    assert not np.array_equal(result[0, 2], result[0, 8])


def test_tiny_and_constant_channels_use_epsilon_floor_rather_than_adding_epsilon():
    values = np.zeros((12, 1000), dtype=np.float32)
    values[0] = 3.25
    values[1] = np.where(np.arange(1000) % 2, 2e-8, -2e-8)
    values[2] = np.where(np.arange(1000) % 2, 2e-6, -2e-6)
    original = values.copy()
    result = normalize_input(values)
    np.testing.assert_array_equal(values, original)
    np.testing.assert_array_equal(result, independent_population_normalization(values))
    np.testing.assert_array_equal(result[0, 0], np.zeros(1000, dtype=np.float32))
    np.testing.assert_allclose(np.abs(result[0, 1]), 0.02, rtol=1e-6)
    np.testing.assert_allclose(np.abs(result[0, 2]), 1.0, rtol=1e-6)


def test_input_is_converted_to_float32_before_population_statistics_and_is_not_modified():
    values = np.full((12, 1000), 100_000_000, dtype=np.float64)
    values[:, ::2] += 1.0  # These variations disappear in the upstream float32 input domain.
    original = values.copy()
    result = normalize_input(values)
    np.testing.assert_array_equal(values, original)
    np.testing.assert_array_equal(result, independent_population_normalization(values))
    assert result.dtype == np.float32


@pytest.mark.parametrize("shape", [(1000, 12), (12, 999), (12, 1001), (11, 1000), (13, 1000), (1, 12, 1000), (12,), ()])
def test_wrong_shapes_are_rejected_without_cropping_padding_or_reshaping(shape):
    with pytest.raises(ValueError):
        normalize_input(np.zeros(shape, dtype=np.float32))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_input_is_rejected(value):
    samples = np.zeros((12, 1000), dtype=np.float32)
    samples[3, 17] = value
    with pytest.raises(ValueError, match="有限"):
        normalize_input(samples)


def test_finite_float32_values_whose_population_statistics_overflow_are_rejected():
    samples = np.zeros((12, 1000), dtype=np.float32)
    samples[0] = np.where(np.arange(1000) % 2, 1e30, -1e30)
    with pytest.raises(ValueError, match="归一化"):
        normalize_input(samples)


def test_values_outside_float32_domain_are_rejected_instead_of_returning_invalid_model_input():
    samples = np.zeros((12, 1000), dtype=np.float64)
    samples[0, 0] = np.finfo(np.float64).max
    with np.errstate(over="ignore"):
        with pytest.raises(ValueError, match="有限"):
            normalize_input(samples)


@pytest.mark.parametrize("values", [[[1.0], [2.0, 3.0]], [["not-a-signal"] * 1000] * 12])
def test_malformed_numeric_arrays_fail_without_model_execution(values):
    with pytest.raises(ValueError):
        normalize_input(values)
