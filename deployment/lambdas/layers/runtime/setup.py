#!/usr/bin/env python3
# pylint: disable=unspecified-encoding

import pkg_resources
import setuptools


with open('requirements.txt') as fh:
    requirements = [str(r) for r in pkg_resources.parse_requirements(fh)]

setuptools.setup(
    name='runtime',
    version='0.0.1',
    description='metapackage for runtime dependencies for GPL Lambda functions',
    author='UMCCR and contributors',
    license='GPLv3',
    packages=setuptools.find_packages(),
    install_requires=requirements,
)
