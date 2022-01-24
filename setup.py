import os
from setuptools import setup, find_packages


long_description = (
    "pyncei provides tools to request data from the [Climate Data Online"
    " Web Services v2 API](http://www.ncdc.noaa.gov/cdo-web/webservices/v2#gettingStarted)"
    " provided by NOAA's National Centers for Environmental information (formerly"
    " the National Center for Climate Data)."
    "\n\n"
    " Install with:"
    "\n\n"
    "```\n"
    "pip install pyncei\n"
    "```"
    "\n\n"
    "Learn more:\n\n"
    "+ [GitHub repsository](https://github.com/adamancer/pyncei)\n"
    "+ [Documentation](https://pyncei.readthedocs.io/en/latest/)"
)

setup(
    name="pyncei",
    maintainer="Adam Mansur",
    maintainer_email="mansura@si.edu",
    description="Access data from NOAA's Climate Data Online Web Services v2 API",
    long_description=long_description,
    long_description_content_type="text/markdown",
    version="1.0",
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
    url="https://github.com/adamancer/pyncei.git",
    author="adamancer",
    author_email="mansura@si.edu",
    license="MIT",
    packages=find_packages(),
    install_requires=["pandas", "requests", "requests-cache"],
    include_package_data=True,
    zip_safe=False,
)
