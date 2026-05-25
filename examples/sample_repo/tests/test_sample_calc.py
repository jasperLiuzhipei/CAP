from sample_calc import apply_discount


def test_apply_discount_uses_rate_as_percentage() -> None:
    assert apply_discount(100.0, 0.15) == 85.0

