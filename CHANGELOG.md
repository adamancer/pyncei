Changelog
=========

All notable changes to this project will be documented in this file,
beginning with version 1.0.

The format is based on [Keep a
Changelog](https://keepachangelog.com/en/1.0.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

\[1.0\]
--------------

### Added

-   Added `NCEIResponse` class to handle responses from the API and
    output results to csv or a pandas DataFrame
-   Added tests

### Changed

-   Renamed `NCEIReader` to `NCEIBot`
-   Renamed method kwargs to match names used by NCEI
-   Query parameters are no longer validated locally by default. Set the
    `validate_params` attribute to True to re-enable this behavior.
-   Added url and retrieval date and time to data returned by the
    various get methods
-   Users can now specify the path to a cache file when creating an
    `NCEIBot` object
-   Info and debug messages now use the logging module instead of print
-   Revised project documentation

### Removed

-   Removed convenience get methods (for example, `get_dataset()`) that
    returned data for a single entity. Pass an id argument to the get
    functions (for example, `get_datasets()`) to achieve the same
    result.
-   Removed count kwarg from get methods. Use the `count()` method on an
    NCEIResponse instead to get a count of records returned so far. Use
    the `total()` method to get a count of the total number of records
    available for the current query.
-   Removed `find_in_endpoint()`, `find_all()`, and `map_name()`
    methods. The `find_ids()` method replaces all three methods.
