#!/usr/bin/env python3
"""Setup script for PyReborn."""

from setuptools import setup, find_packages
import os

# Read README file
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

# Read version from __init__.py
def get_version():
    version_file = os.path.join("pyreborn", "__init__.py")
    with open(version_file, "r") as f:
        for line in f:
            if line.startswith("__version__"):
                return line.split('"')[1]
    return "0.1.0"

setup(
    name="pyreborn",
    version=get_version(),
    author="PyReborn Contributors",
    author_email="",
    description="A Python library for connecting to Reborn servers",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/pyReborn",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Games/Entertainment",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: System :: Networking",
    ],
    python_requires=">=3.8",
    install_requires=[
        # No external dependencies - uses only standard library
    ],
    extras_require={
        "dev": [
            "pytest>=6.0",
            "pytest-cov",
            "flake8",
            "black",
            "mypy",
        ],
        "examples": [
            # No additional dependencies for examples
        ],
    },
    entry_points={
        "console_scripts": [
            "pyreborn-test=pyreborn.examples.test_connection:main",
        ],
    },
    include_package_data=True,
    package_data={
        "pyreborn": ["py.typed"],
    },
    project_urls={
        "Bug Reports": "https://github.com/yourusername/pyReborn/issues",
        "Source": "https://github.com/yourusername/pyReborn",
        "Documentation": "https://github.com/yourusername/pyReborn/blob/main/docs/REBORN_PROTOCOL_GUIDE.md",
    },
    keywords="reborn game networking protocol client library",
    zip_safe=False,
)