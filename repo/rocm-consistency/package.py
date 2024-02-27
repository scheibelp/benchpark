# Copyright 2013-2024 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

from spack.package import *
from spack.package_base import PackageBase


class RocmConsistency(PackageBase):
    with when("+rocm"):
        for ver in [
            "5.1.0",
            "5.1.3",
            "5.2.0",
            "5.2.1",
            "5.2.3",
            "5.3.0",
            "5.3.3",
            "5.4.0",
            "5.4.3",
            "5.5.0",
            "5.5.1",
            "5.6.0",
            "5.6.1",
            "5.7.0",
            "5.7.1",
            "6.0.0",
            "6.0.2",
        ]:
            depends_on(f"hsakmt-roct@{ver}", when=f"^hip@{ver}")
            depends_on(f"hsa-rocr-dev@{ver}", when=f"^hip@{ver}")
            depends_on(f"comgr@{ver}", when=f"hip@{ver}")
            depends_on(f"llvm-amdgpu@{ver} +rocm-device-libs", when=f"hip@{ver}")
            depends_on(f"rocminfo@{ver}", when=f"hip@{ver}")
            depends_on(f"roctracer-dev-api@{ver}", when=f"hip@{ver}")
