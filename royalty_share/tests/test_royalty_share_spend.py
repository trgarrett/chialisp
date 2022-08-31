from royalty_share_spend import calculate_cat_royalty_address

import pytest

class TestRoyaltyShareSpend:

    def test_calculate_royalty_address_lky8(self):
        (royalty_address, royalty_puzzle_hash) = calculate_cat_royalty_address('xch18zttqcg25pjwhuf7s4kptpe3kslp7nzwkj5k6vrsxp8tt0nke8cqhz785s', 'e5a8af7124c2737283838e6797b0f0a5293fc81aca1ffd2720f8506c23f2ad88')
        assert royalty_address == "xch1pdw4wj8z8shn0lszh2n7nffwyh8vf24gujlzzq20k5wjg4p0hkxqa6akyr"

    def test_calculate_royalty_address_sbx(self):
        (royalty_address, royalty_puzzle_hash) = calculate_cat_royalty_address('xch18zttqcg25pjwhuf7s4kptpe3kslp7nzwkj5k6vrsxp8tt0nke8cqhz785s', 'a628c1c2c6fcb74d53746157e438e108eab5c0bb3e5c80ff9b1910b3e4832913')
        assert royalty_address == "xch193cp9h5h5qx5xw88y43aeszvu6tkrg8s03atwqakaz6lfy8jyukqke8xe3"        