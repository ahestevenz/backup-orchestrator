# -*- coding: utf-8 -*-
"""
setup.py

Setup script for the backup-orchestrator package.

Defines package metadata, dependencies, entry points, and test configuration
for building, distributing, and installing the backup-orchestrator Python package.
"""

from setuptools import find_packages, setup


def readme():
    """
    Read the contents of README.md to use as the long description.

    Returns:
        str: The contents of README.md.
    """
    with open("README.md", encoding="utf-8") as f:
        return f.read()


setup(
    name="backup-orchestrator",
    version="1.0.2",
    description="Backup based on RSYNC command",
    packages=find_packages("src"),
    package_dir={"": "src"},
    long_description=readme(),
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Programming Language :: Python :: 3",
        "Intended Audience :: End Users/Desktop",
    ],
    keywords="backup sync rsync",
    url="https://github.com/ahestevenz/backup-orchestrator",
    author="Ariel Hernandez <ahestevenz@bleiben.ar>",
    author_email="ahestevenz@bleiben.ar",
    license="Proprietary",
    install_requires=[
        "numpy",
        "pexpect",
        "pytest-shutil",
        "loguru",
        "pyyaml",
        "pydantic",
    ],
    test_suite="nose.collector",
    tests_require=["nose"],
    entry_points={
        "console_scripts": [
            "bn-run-backup=backup_orchestrator.scripts.run_backup:main"
        ],
    },
    include_package_data=True,
    zip_safe=True,
)
