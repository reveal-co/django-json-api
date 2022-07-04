#!/usr/bin/env python
from os.path import join

from setuptools import find_packages, setup


# DEPENDENCIES
def requirements_from_pip(filename):
    with open(filename, "r") as pip:
        return [line.strip() for line in pip if not line.startswith("#") and line.strip()]


core_deps = requirements_from_pip("requirements.txt")
dev_deps = requirements_from_pip("requirements_dev.txt")


# DESCRIPTION
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()


setup(
    author="Sharework",
    author_email="root@sharework.co",
    description="JSON API specification for Django services",
    extras_require={"all": dev_deps, "dev": dev_deps},
    install_requires=core_deps,
    long_description=long_description,
    long_description_content_type="text/markdown",
    name="django-json-api",
    package_data={"django_json_api": ["resources/VERSION"]},
    packages=find_packages(),
    python_requires=">=3.8",
    url="https://github.com/share-work/django-json-api",
    version=open(join("django_json_api", "resources", "VERSION")).read().strip(),
    classifiers=[
        "Programming Language :: Python :: 3.8",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
