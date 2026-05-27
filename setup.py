#!/usr/bin/python3

import setuptools
import sys
sys.dont_write_bytecode=True
sys.pycache_prefix=None

setuptools.setup(
    name='dmk-util',
    version='0.1',
    package_dir={"": "src"},
    entry_points={
        'console_scripts': [
            'dmk-util=dmk_util:main',
            ]
    }
)
