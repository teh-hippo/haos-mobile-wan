import unittest

from rootfs.app.gateway import load_or_create_token
from rootfs.app.upstream import (
    MobileConnectionResolver,
    IPhoneUsbUpstream,
    ResolvedUpstream,
    configured_upstream,
)
from rootfs.app.upstream_iphone import IPhoneUsbUpstream as DirectIPhoneUsbUpstream
from rootfs.app.mobile_connection import (
    MobileConnectionResolver as DirectMobileConnectionResolver,
)
from rootfs.app.upstream_models import (
    ResolvedUpstream as DirectResolvedUpstream,
    configured_upstream as direct_configured_upstream,
)


class ImportCompatibilityTests(unittest.TestCase):
    def test_gateway_re_exports_token_loader(self) -> None:
        self.assertTrue(callable(load_or_create_token))

    def test_upstream_module_re_exports_existing_symbols(self) -> None:
        self.assertIs(IPhoneUsbUpstream, DirectIPhoneUsbUpstream)
        self.assertIs(MobileConnectionResolver, DirectMobileConnectionResolver)
        self.assertIs(ResolvedUpstream, DirectResolvedUpstream)
        self.assertIs(configured_upstream, direct_configured_upstream)
