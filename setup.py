#!/usr/bin/env python3
from setuptools import setup, find_packages

setup(
    name="pyreborn",
    version="0.1.0",
    description="Python library for connecting to GServer (Graal Reborn)",
    author="pyReborn Development",
    packages=find_packages(),
    install_requires=[
        "asyncio",
    ],
    python_requires=">=3.7",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
)