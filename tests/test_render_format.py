from wattage.render.format import format_dollars


def test_normal_amounts_use_four_decimal_places() -> None:
    assert format_dollars(0.0024) == "$0.0024"
    assert format_dollars(1.5) == "$1.5000"


def test_genuine_zero_is_zero() -> None:
    assert format_dollars(0.0) == "$0.0000"


def test_sub_cent_amount_that_would_round_to_zero_shows_more_precision() -> None:
    """A real finding must never visually read as $0.0000 -- that looks
    like no waste was found at all, even though the number is honestly
    computed and nonzero."""
    assert format_dollars(0.000018) == "$0.000018"
    assert format_dollars(0.000024) == "$0.000024"


def test_extremely_tiny_amount_still_shows_a_nonzero_digit() -> None:
    assert format_dollars(0.00000015) != "$0.0000"
    assert float(format_dollars(0.00000015).lstrip("$")) > 0
