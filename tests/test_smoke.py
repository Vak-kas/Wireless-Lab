# SPDX-License-Identifier: GPL-3.0-or-later
import wls


def test_package_imports_and_has_version():
    assert wls.__version__ == "0.0.1"
