"""Tools to access data from NOAA's Climate Data Online Web Services v2 API"""

from copy import copy
import csv
from datetime import datetime
import glob
import logging
import os
import re
import time
import urllib.parse

import pandas as pd
import requests
import requests_cache

try:
    import geopandas as gpd
except ImportError:
    pass


logger = logging.getLogger(__name__)


class NCEIBot:
    """Contains functions to request data from the NCEI web services

    Attributes:
        wait (float): time in seconds between requests. NCEI
            allows a maximum of five queries per second.
        validate_params (bool): whether to validate query parameters before
            making a GET request. Defaults to False.
        max_retries (int): number of times to retry requests that fail
            because of temporary connectivity or server lapses. Retries
            use an exponential backoff. Defaults to 12.

    The get functions described below use a common set of keyword arguments.
    The sortorder, limit, offset, and max arguments can be used in
    any get function; other keywords vary by endpoint. Most values appear to
    be case-sensitive. Query validation, if enabled, should capture
    most but not all case errors.

    Args:
        datasetid (str or list): the id or name of a NCEI dataset. Multiple
            values allowed for most functions. Examples: GHCND; PRECIP_HLY;
            Weather Radar (Level III).
        datacategoryid (str or list): the id or name of a NCEI data category.
            Data categories are broader than data types. Multiple values
            allowed. Examples: TEMP, WXTYPE, Degree Days.
        datatypeid (str or list): the id or name of a data type. Multiple values
            allowed. Examples: TMIN; SNOW; Long-term averages of fall growing
            degree days with base 70F.
        locationid (str or list): the id or name of a location. Multiple values
            allowed. If a name is given, the script will try to map it to an id.
            Examples: Maryland; FIPS:24; ZIP:20003; London, UK.
        stationid (str or list): the id of name of a station in the NCEI
            database. Multiple values allowed. Examples: COOP:010957.
        startdate (str or datetime): the earliest date available
        enddate (str or datetime): the latest date available
        sortfield (str): field by which to sort the query results. Available
            sort fields vary by endpoint.
        sortorder (str): specifies whether sort is ascending or descending.
            Must be 'asc' or 'desc'.
        limit (int): number of records to return per query
        offset (int): index of the first record to return
        max (int): maximum number of records to return. Not part of the API.
    """

    def __init__(self, token, wait=0.2, cache_name=None, **cache_kwargs):
        """Initializes NCEIBot object

        Args:
            token (str): NCEI token
            wait (float or int): time in seconds to wait between requests
            cache_name (str): path to cache
            cache_kwargs: any keyword argument accepted by requests_cache.CachedSession
        """

        self.validate_params = False
        self.max_retries = 12

        # Queries are capped at five per second, so enforce that with
        # a minimum wait time of 0.2 seconds
        if wait < 0.2:
            self.wait = 0.2
        else:
            self.wait = wait

        if cache_kwargs and not cache_name:
            raise Exception("Must specify cache_name if cache_kwargs are provided")

        # Cache queries using requests_cache
        if cache_name:
            self._cache = True
            self._session = requests_cache.CachedSession(cache_name, **cache_kwargs)
        else:
            self._cache = False
            self._session = requests.Session()

        # Lazy load __version__ to prevent circular import error
        from . import __version__

        self._session.headers.update(
            {"token": token, "User-Agent": f"pyncei v{__version__}"}
        )

        self._validators = {
            "datacategoryid": self._check_name,
            "datasetid": self._check_name,
            "datatypeid": self._check_name,
            "enddate": self._check_date,
            "extent": self._check_extent,
            "limit": self._check_limit,
            "locationid": self._check_name,
            "locationcategoryid": self._check_name,
            "max": self._check_positive_integer,
            "offset": self._check_positive_integer,
            "stationid": self._check_name,
            "startdate": self._check_date,
            "sortfield": self._check_sortfield,
            "sortorder": self._check_sortorder,
            "units": self._check_units,
        }

        # List of fields that can occur more than once in a given query.
        # This list may need to be adjusted depending on the endpoint;
        # for example, the data endpoint allows only one dataset to be passed.
        self._allow_multiple = [
            "datacategoryid",
            "datasetid",
            "datatypeid",
            "locationid",
            "locationcategoryid",
            "stationid",
        ]

        # List of endpoints
        self._endpoints = [
            "datacategories",
            "datasets",
            "datatypes",
            "locations",
            "locationcategories",
            "stations",
        ]

        # Create name lookups to help users map to ids needed for querying
        self._lookups = {}
        self._filepath = os.path.join(os.path.dirname(__file__), "files")
        try:
            os.makedirs(self._filepath)
        except OSError:
            for fp in glob.iglob(os.path.join(self._filepath, "*.csv")):
                fn = os.path.splitext(os.path.basename(fp))[0]
                self._lookups[fn] = {}
                with open(fp, encoding="utf-8-sig", newline="") as f:
                    rows = csv.reader(f, delimiter=",", quotechar='"')
                    try:
                        next(rows)
                    except StopIteration:
                        pass
                    else:
                        for row in rows:
                            for item in row:
                                self._lookups[fn][item.lower()] = tuple(row)

    def get_data(self, **kwargs):
        """Retrieves historical climate data matching the given parameters

        See :py:class:`~pyncei.bot.NCEIBot` for more details about each
        keyword argument.

        Args:
            datasetid (str): Required. Only one value allowed.
            startdate (str or datetime): Required. Returned stations will
                have data for the specified dataset/type from on or after
                this date.
            enddate (str or datetime): Required. Returned stations will
                have data for the specified dataset/type from on or before
                this date.
            datatypeid (str or list): Optional
            locationid (str or list): Optional
            stationid (str or list): Optional
            units (str): Optional. One of 'standard' or 'metric'.
            sortfield (str): Optional. If provided, must be one of 'datatype',
                'date', or 'station'.
            sortorder (str): Optional
            limit (int): Optional
            offset (int): Optional
            max (int): Optional

        Returns:
            List of dicts containing historical weather data
        """
        url = "http://www.ncdc.noaa.gov/cdo-web/api/v2/data"
        required = ["datasetid", "startdate", "enddate", "units"]
        optional = [
            "datatypeid",
            "locationid",
            "stationid",
            "sortfield",
            "sortorder",
            "limit",
            "offset",
            "includemetadata",
        ]
        # Assign default unit. Returned values are nonsense without this.
        if not kwargs.get("units"):
            kwargs["units"] = "metric"
        self._allow_multiple.remove("datasetid")
        url, params = self._prepare_query(url, [], kwargs, required, optional)
        self._allow_multiple.append("datasetid")
        return self._get(url, params)

    def get_datasets(self, datasetid=None, **kwargs):
        """Returns data from the NCEI dataset endpoint

        See :py:class:`~pyncei.bot.NCEIBot` for more details about each
        keyword argument.

        Args:
            datasetid (str): a single dataset to return information about. Optional.
                The kwargs are ignored if this is provided.
            datatypeid (str or list): Optional
            locationid (str or list): Optional
            stationid (str or list): Optional
            sortfield (str): Optional. If provided, must be one of 'id',
                'name', 'mindate', 'maxdate', or 'datacoverage'.
            sortorder (str): Optional
            limit (int): Optional
            offset (int): Optional
            max (int): Optional

        Returns:
            List of dicts containing metadata for all matching datasets
        """
        url = "http://www.ncdc.noaa.gov/cdo-web/api/v2/datasets"
        required = []
        optional = [
            "datatypeid",
            "locationid",
            "stationid",
            "startdate",
            "enddate",
            "sortfield",
            "sortorder",
            "limit",
            "offset",
        ]
        url, params = self._prepare_query(url, datasetid, kwargs, required, optional)
        return self._get(url, params)

    def get_data_categories(self, datacategoryid=None, **kwargs):
        """Returns codes and labels for NCDI data categories

        See :py:class:`~pyncei.bot.NCEIBot` for more details about each
        keyword argument.

        Args:
            datacategoryid (str): a single data category to return information
                about. Optional. The kwargs are ignored if this is provided.
            datasetid (str or list): Optional
            locationid (str or list): Optional
            stationid (str or list): Optional
            startdate (str or datetime): Optional
            enddate (str or datetime): Optional
            sortfield (str): Optional. If provided, must be one of 'id',
                'name', 'mindate', 'maxdate', or 'datacoverage'.
            sortorder (str): Optional
            limit (int): Optional
            offset (int): Optional
            max (int): Optional

        Returns:
            List of dicts containing metadata for all matching data
            categories
        """
        url = "http://www.ncdc.noaa.gov/cdo-web/api/v2/datacategories"
        required = []
        optional = [
            "datasetid",
            "locationid",
            "stationid",
            "startdate",
            "enddate",
            "sortfield",
            "sortorder",
            "limit",
            "offset",
        ]
        url, params = self._prepare_query(
            url, datacategoryid, kwargs, required, optional
        )
        return self._get(url, params)

    def get_data_types(self, datatypeid=None, **kwargs):
        """Returns information about NCEI data categories

        See :py:class:`~pyncei.bot.NCEIBot` for more details about each
        keyword argument.

        Args:
            datatypeid (str): a single data type to return information about.
                Optional. The kwargs are ignored if this is provided.
            datasetid (str or list): Optional
            locationid (str or list): Optional
            stationid (str or list): Optional
            datacategoryid (str or list): Optional
            startdate (str or datetime): Optional
            enddate (str or datetime): Optional
            sortfield (str): Optional. If provided, must be one of 'id',
                'name', 'mindate', 'maxdate', or 'datacoverage'.
            sortorder (str): Optional
            limit (int): Optional
            offset (int): Optional
            max (int): Optional

        Returns:
            List of dicts containing metadata for all matching data types
        """
        url = "http://www.ncdc.noaa.gov/cdo-web/api/v2/datatypes"
        required = []
        optional = [
            "datasetid",
            "locationid",
            "stationid",
            "datacategoryid",
            "startdate",
            "enddate",
            "sortfield",
            "sortorder",
            "limit",
            "offset",
        ]
        url, params = self._prepare_query(url, datatypeid, kwargs, required, optional)
        return self._get(url, params)

    def get_location_categories(self, locationcategoryid=None, **kwargs):
        """Returns information about NCEI location categories

        See :py:class:`~pyncei.bot.NCEIBot` for more details about each
        keyword argument.

        Args:
            locationcategoryid (str): a single location category to return
                information about. Optional. The kwargs are ignored if this is
                provided.
            datasetid (str or list): Optional
            sortfield (str): Optional. If provided, must be one of 'id' or
                'name'.
            sortorder (str): Optional
            limit (int): Optional
            offset (int): Optional
            max (int): Optional

        Returns:
            List of dicts containing metadata about location categories
        """
        url = "http://www.ncdc.noaa.gov/cdo-web/api/v2/locationcategories"
        required = []
        optional = [
            "datasetid",
            "startdate",
            "enddate",
            "sortfield",
            "sortorder",
            "limit",
            "offset",
        ]
        url, params = self._prepare_query(
            url, locationcategoryid, kwargs, required, optional
        )
        return self._get(url, params)

    def get_locations(self, locationid=None, **kwargs):
        """Returns metadata for locations matching the given parameters

        See :py:class:`~pyncei.bot.NCEIBot` for more details about each
        keyword argument.

        Args:
            locationid (str): a single location to return information about.
                Optional. The kwargs are ignored if this is provided.
            datasetid (str or list): Optional
            locationcategoryid (str or list): Optional
            datacategoryid (str or list): Optional
            sortfield (str): Optional. If provided, must be one of 'id',
                'name', 'mindate', 'maxdate', or 'datacoverage'.
            sortorder (str): Optional
            limit (int): Optional
            offset (int): Optional
            max (int): Optional

        Returns:
            List of dicts containing metadata for all matching locations
        """
        url = "http://www.ncdc.noaa.gov/cdo-web/api/v2/locations"
        required = []
        optional = [
            "datasetid",
            "locationcategoryid",
            "datacategoryid",
            "startdate",
            "enddate",
            "sortfield",
            "sortorder",
            "limit",
            "offset",
        ]
        url, params = self._prepare_query(url, locationid, kwargs, required, optional)
        return self._get(url, params)

    def get_stations(self, stationid=None, **kwargs):
        """Returns metadata for stations matching the given parameters

        See :py:class:`~pyncei.bot.NCEIBot` for more details about each
        keyword argument.

        Args:
            stationid (str): a single station to return information about.
                Optional. The kwargs are ignored if this is provided.
            datasetid (str or list): Optional
            locationid (str or list): Optional
            datacategoryid (str or list): Optional
            datatypeid (str or list): Optional
            extent (str or iterable): comma-delimited bounding box of form
                'min_lat, min_lng, max_lat, max_lng' or equivalent iterable.
                Optional.
            sortfield (str): Optional. If provided, must be one of 'id',
                'name', 'mindate', 'maxdate', or 'datacoverage'.
            sortorder (str): Optional
            limit (int): Optional
            offset (int): Optional
            max (int): Optional

        Returns:
            List of dicts containing metadata for all matching stations
        """
        url = "http://www.ncdc.noaa.gov/cdo-web/api/v2/stations"
        required = []
        optional = [
            "datasetid",
            "locationid",
            "datacategoryid",
            "datatypeid",
            "extent",
            "startdate",
            "enddate",
            "sortfield",
            "sortorder",
            "limit",
            "offset",
        ]
        url, params = self._prepare_query(url, stationid, kwargs, required, optional)
        return self._get(url, params)

    def find_ids(self, term=None, endpoints=None):
        """Find key terms that match the search string for the given endpoints

        Args:
            term (str): the term to search for. If None, returns a list of all
                available terms for the specified endpoint(s).
            endpoints (str or list): name of one or more NCEI endpoints

        Returns:
            List of (endpoint, id, name) for matching key terms from the
            specified endpoint
        """

        if endpoints is None:
            endpoints = sorted(self._lookups)
        if isinstance(endpoints, str):
            endpoints = [endpoints]

        ids = []
        for endpoint in endpoints:
            try:
                lookup = self._lookups[endpoint.lower()]
            except KeyError:
                raise
            else:
                try:
                    matches = [lookup[term.lower()]]
                except KeyError:
                    matches = [v for k, v in lookup.items() if term.lower() in k]
                ids.extend(sorted({(endpoint, *m) for m in matches}))
        return ids

    def refresh_lookups(self, keys=None):
        """Update the csv files used to populate the endpoint lookups

        Args:
            keys (list): list of endpoints to populate. If empty,
                everything but stations will be populated.

        Returns:
            None
        """
        endpoints = {
            "datasets": self.get_datasets,
            "datacategories": self.get_data_categories,
            "datatypes": self.get_data_types,
            "locationcategories": self.get_location_categories,
            "locations": self.get_locations,
            "stations": self.get_stations,
        }
        if keys is None:
            keys = [k for k in endpoints if k != "stations"]
        elif not isinstance(keys, list):
            keys = [keys]
        for key in keys:
            try:
                response = endpoints[key]()
            except KeyError as exc:
                raise Exception(f"{key} is not a valid id") from exc
            else:
                fp = os.path.join(self._filepath, key + ".csv")
                with open(fp, "w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.writer(f, dialect="excel")
                    writer.writerow(["id", "name"])
                    for result in response.values():
                        row = [result["id"], result["name"]]
                        writer.writerow(row)

    def _get_with_retry(self, url, params):
        """Retries a get request with an exponential backoff

        Args:
            url (str): NCDI webservice url
            params (dict): query parameters

        Returns:
            response to given request
        """
        for i in range(self.max_retries):
            try:
                resp = self._session.get(url, params=self._encode_params(params))
                # Retry if status code indicates a temporary server problem
                if resp.status_code == 503:
                    raise requests.exceptions.ConnectionError(
                        f"Request failed: {resp.url} (status_code={resp.status_code})"
                    )
                return resp
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
            ) as err:
                wait = 2 ** i
                print(
                    f"Retrying temporarily failed request in {wait}s"
                    f" (url={url}, params={params}, error='{err}')"
                )
                time.sleep(wait)
        raise Exception(f"Request failed (url={url}, params={params})")

    def _get(self, url, params):
        """Retrieves all matching records for a given url and parameter set

        Args:
            url (str): NCDI webservice url
            params (dict): query parameters

        Returns:
            List of dicts containing the requested data
        """
        # Many of the NCDI webservies have two different endpoints: one for
        # a single, specific argument (for example, a station id), another
        # for a query string. Here, specific requests are given a trailing
        # backslash as a lazy way to tell the two types of reqeuests apart.
        if not url.endswith("/"):
            try:
                offset = params["offset"]
            except KeyError:
                params["offset"] = offset = 1
            else:
                # Offsets 0 and 1 both return the same record. Specifying
                # an offset of 1 makes subsequent offsets (made by adding
                # the limit to the last offset) start at the right record.
                if not offset:
                    params["offset"] = offset = 1
            # Minimize number of queries required to retrieve data
            # by adjusting limit based on total number of records
            try:
                limit = params["limit"]
            except KeyError:
                params["limit"] = limit = 1000

            try:
                total = params.pop("max")
            except KeyError:
                total = limit if limit < 1000 else 1e12  # any large number works
            else:
                if total < 1000:
                    params["limit"] = limit = total
                else:
                    params["limit"] = limit = 1000

        else:
            total = limit = 1

        logger.debug("Final parameter set:")
        if total > 0:
            logger.debug(f"total: {total}")
        for key in params:
            logger.debug(f"{key}: {params[key]}")

        response = NCEIResponse()
        while response.count() < total:

            logger.info("Requesting data")

            # NCEI does not like encoded colons, so encode the query string first
            resp = self._get_with_retry(url, params)
            if resp.status_code == 200:
                logger.info(f"Resolved {resp.url}")

                # Enforce a wait period between requests
                if self._cache and not resp.from_cache:
                    logger.info("Caching request")
                    time.sleep(self.wait)
                elif not self._cache:
                    logger.info(f"Waiting {self.wait} seconds...")
                    time.sleep(self.wait)
                else:
                    logger.info("URL was retrieved from cache")

                response.append(resp)
                if response.total() < total:
                    total = response.total()
                logger.info(f"{response.count():,}/{total:,} records retrieved")

                try:
                    params["offset"] += limit
                except KeyError:
                    params["offset"] = limit
            else:
                raise Exception(
                    f"Failed to resolve {resp.url} ({resp.status_code}: {resp.text}"
                )
        return response

    def _prepare_query(self, url, endpoint_id, kwargs, required, optional):
        """Validate query

        Args:
            url (str): url to NCEI endpoint
            endpoint_id (tuple): id from the endpoint
            kwargs (dict): keyed query parameters
            required (list): required fields for endpoint
            optional (list): optional fields for endpoint

        Returns:
            Tuple (url string, paramter dict) if query is valid
        """
        logger.info(f"Preparing request to {url}")
        if endpoint_id:
            if kwargs:
                logger.warning(f"Ignoring kwargs: {kwargs}")
            # Return URL for a specific endpoint
            return url + f"/{endpoint_id}/", {}
        if self.validate_params:
            # Extend optional with helper fields
            optional.extend(["max"])
            # Confirm that all required fields are present
            missing = [key for key in required if not key in kwargs]
            if missing:
                raise Exception(f'Required parameters missing: {", ".join(missing)}')
            # Check that all fields in kwargs are valid
            invalid = [key for key in kwargs if not key in required + optional]
            if invalid:
                raise Exception(f'Invalid parameters found: {", ".join(invalid)}')
            # Clean up kwargs
            kwargs = self._check_kwargs(kwargs, url.split("/").pop())
        else:
            # Try to map names to ids even if validation is disabled
            ids = {
                k: v
                for k, v in kwargs.items()
                if self._validators[k] in (self._check_name, self._check_extent)
            }
            kwargs.update(self._check_kwargs(ids, url.split("/").pop()))
        # Query string endpoint
        return url, kwargs

    def _check_kwargs(self, kwargs, endpoint):
        """Validates values given for query parameters

        Args:
            kwargs (dict): query parameters
            endpoint (str): name of valid NCEI endpoint

        Returns:
            Dict containing cleaned up values for kwargs
        """
        errors = []
        # Check kwargs against validation functions
        for key in kwargs.keys():
            vals = kwargs[key]
            # Extent can be an iterable, so treat lists in this key as one value
            if isinstance(vals, (list, tuple)) and key == "extent":
                vals = [vals]
            if not isinstance(vals, (list, tuple)):
                vals = [vals]
            validated = []
            for val in vals:
                try:
                    value, status = self._validators[key](val, key, endpoint)
                except KeyError:
                    # Catches bad parameter names. In practice, this should
                    # never occur because bad params should be weeded out
                    # beforehand.
                    errors.append(f"{key} is not a valid parameter")
                else:
                    if status is False:
                        errors.append(f"{key}: {value} is invalid")
                    else:
                        validated.append(value)
                        logger.info(f"{key}: {value} is valid")

            if not errors:

                # Catch multiple values passed to key that only accepts one
                if not key in self._allow_multiple:
                    if len(validated) > 1:
                        errors.append(f"{key} only accepts one value")
                    else:
                        validated = validated[0]

                # Map helper fields to corresponding query fields
                try:
                    self._endpoints.index(re.sub(r"id$", "", key))
                except ValueError:
                    kwargs[key] = validated

        if errors:
            s = "" if len(errors) == 1 else "s"
            raise Exception(f'Parameter error{s}: {"; ".join(errors)}')

        return kwargs

    def _check_name(self, value, key, endpoint):
        """Map name to id for a given key, if possible

        Args:
            value (str): an identifer or name
            key (str): name of field being checked
            endpoint (str): name of current NCEI endpoint

        Returns:
            Tuple (id, True) if name is valid, or tuple
            (error message, False) if not.
        """
        endpoint = [e for e in self._endpoints if e.startswith(key.rstrip("deis"))][0]
        try:
            ids = self.find_ids(value, endpoint)
            if len(ids) == 1:
                return ids[0][1], True
        except KeyError:
            # Allow original value through if no lookup is configured
            logger.warning(f"No lookup list found for {endpoint}")
            return value, True
        except AttributeError:
            pass
        return f"Failed to map '{value}' to an id", False

    @staticmethod
    def _check_date(date, key, endpoint):
        """Validate and formate date

        Args:
            date (str or dateime.datetime): date or equivalent
            key (str): name of field being checked
            endpoint (str): name of current NCEI endpoint

        Returns:
            Tuple (date string, True) if date is valid, or tuple
            (error message, False) if not.
        """
        try:
            return date.strftime("%Y-%m-%d"), True
        except AttributeError:
            try:
                datetime.strptime(date, "%Y-%m-%d")
            except (TypeError, ValueError):
                pass
            else:
                return date, True
        return "Must be a datetime object or string formatted as %Y-%m-%d", False

    @staticmethod
    def _check_extent(extent, key, endpoint):
        """Validate extent query parameter

        Args:
            extent (str or iterable): comma-delimited bounding box of form
                'min_lat, min_lng, max_lat, max_lng' or equivalent iterable
            key (str): name of field being checked
            endpoint (str): name of current NCEI endpoint

        Returns:
            Tuple (extent string, True) if extent is valid, or tuple
            (error message, False) if not.
        """
        if isinstance(extent, str):
            extent = [s.strip() for s in extent.split(",")]
        min_lat, min_lng, max_lat, max_lng = [float(c) for c in extent]
        if min_lat < max_lat and min_lng < max_lng:
            return ",".join([str(s) for s in extent]), True
        return 'Must be string/iterable of "min_lat, min_lng, max_lat, max_lng"', False

    @staticmethod
    def _check_sortfield(value, key, endpoint):
        """Validate sortfield query parameter

        Args:
            value (str): name of sort field. Sort fields vary by endpoint.
            key (str): name of field being checked
            endpoint (str): name of current NCEI endpoint

        Returns:
            Tuple (sort field, True) if sort field is valid, or tuple
            (error message, False) if not.
        """
        fields = {
            "data": ["datatype", "date", "station"],
            "datasets": ["id", "name", "mindate", "maxdate", "datacoverage"],
            "datacategories": ["id", "name"],
            "locationcategories": ["id", "name"],
            "locations": ["id", "name", "mindate", "maxdate", "datacoverage"],
            "stations": ["id", "name", "mindate", "maxdate", "datacoverage"],
        }
        try:
            value = value.lower()
        except AttributeError:
            pass
        else:
            if value in fields[endpoint]:
                return value, True
        return f'Must be one of the following: {", ".join(fields[endpoint])}', False

    @staticmethod
    def _check_sortorder(value, key, endpoint):
        """Validate sort order

        Args:
            value (str): 'asc' or 'desc'
            key (str): name of field being checked
            endpoint (str): name of current NCEI endpoint

        Returns:
            Tuple (validated string, True) if order is valid, or tuple
            (error message, False) if not.
        """
        valid = ["asc", "desc"]
        try:
            value = value.lower()
        except AttributeError:
            pass
        else:
            if value in valid:
                return value, True
        return f'Must be one of the following: {", ".join(valid)}', False

    @staticmethod
    def _check_units(value, key, endpoint):
        """Validate units

        Args:
            value (str): 'standard' or 'metric'
            key (str): name of field being checked
            endpoint (str): name of current NCEI endpoint

        Returns:
            Tuple (validated string, True) if order is valid, or tuple
            (error message, False) if not.
        """
        valid = ["standard", "metric"]
        try:
            value = value.lower()
        except AttributeError:
            pass
        else:
            if value in valid:
                return value, True
        return f'Must be one of the following: {", ".join(valid)}', False

    @staticmethod
    def _check_limit(value, key, endpoint):
        """Validate limit

        Args:
            value (str or int): integer to validate
            key (str): name of field being checked
            endpoint (str): name of current NCEI endpoint

        Returns:
            Tuple (validated integer, True) if limit is valid, or tuple
            (error message, False) if not.
        """
        try:
            value = int(value)
        except (TypeError, ValueError):
            pass
        else:
            if 0 < value <= 1000:
                return value, True
        return "Must be an integer between 1 and 1000, inclusive", False

    @staticmethod
    def _check_positive_integer(value, key, endpoint):
        """Validate positive integer

        Args:
            value (str or int): integer to validate
            key (str): name of field being checked
            endpoint (str): name of current NCEI endpoint

        Returns:
            Tuple (validated integer, True) if number is valid, or tuple
            (error message, False) if not.
        """
        try:
            value = int(value)
        except (TypeError, ValueError):
            pass
        else:
            if value >= 0:
                return value, True
        return "Must be an integer greater than or equal to 0", False

    @staticmethod
    def _encode_params(params, safe=":,"):
        param_list = []
        for key, vals in params.items():
            for val in vals if isinstance(vals, (list, tuple)) else [vals]:
                param_list.append((key, val))
        return urllib.parse.urlencode(param_list, safe=safe)


class NCEIResponse(list):
    """Wraps results of one or more calls to the NCEI API

    Extends list. Each response is stored as an entry in the list.
    """

    #: list used to order the keys in the NCEI data
    key_order = [
        "id",
        "uid",
        "name",
        "station",
        "latitude",
        "longitude",
        "elevation",
        "elevationUnit",
        "datacoverage",
        "date",
        "mindate",
        "maxdate",
        "datatype",
        "attributes",
        "value",
        "url",
        "retrieved",
    ]

    #: dict mapping NCEI fields to date formats
    date_formats = {
        "date": "%Y-%m-%dT%H:%M:%S",
        "maxdate": "%Y-%m-%d",
        "mindate": "%Y-%m-%d",
        "retrieved": "%Y-%m-%dT%H:%M:%S",
    }

    def __str__(self):
        return (
            f"<{self.__class__.__name__} responses={len(self)}"
            f" count={self.count()} total={self.total()}>"
        )

    def __repr__(self):
        return str(self)

    def values(self):
        """Gets the results from all responses

        Returns:
            generator of dicts
        """
        keys = None
        for resp in self:
            metadata = {
                "url": resp.url,
                "retrieved": datetime.strptime(
                    resp.headers["Date"], "%a, %d %b %Y %H:%M:%S %Z"
                ).isoformat(),
            }
            for val in self._get_results(resp):
                if val:
                    val.update(metadata)

                if not keys:
                    keys = set(val.keys())
                    if keys - set(self.key_order):
                        raise KeyError(
                            f"Found unordered keys: {keys - set(self.key_order)}"
                        )

                yield {k: val[k] for k in self.key_order if k in keys}

    def first(self):
        """Gets the first result from the compiled responses

        Returns:
            dict
        """
        for val in self.values():
            return val

    def count(self):
        """Counts the number of results that have been returned

        Returns:
            number of records returned as int
        """
        return sum([len(self._get_results(r)) for r in self])

    def total(self):
        """Counts the total number of results available for all URLs

        Returns:
            total number of records matching the responses as int
        """
        urls = {}
        for resp in self:
            # Group by url with pagination parameters removed
            url = re.sub(r"\b(offset|limit|max)=\d+\b", "&", resp.url).strip("&")
            try:
                urls.setdefault(url, int(resp.json()["metadata"]["resultset"]["count"]))
            except KeyError:
                urls.setdefault(url, 1)
        return sum(urls.values())

    def to_csv(self, path):
        """Writes data to a CSV

        Args:
            path (str): path to csv
        """
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, dialect="excel")
            keys = None
            for row in self.values():
                row = row.copy()
                if not keys:
                    keys = row.keys()
                    writer.writerow(keys)
                writer.writerow([row[k] for k in keys])

    def to_dataframe(self):
        """Writes data to a dataframe

        Returns:
            pandas.DataFrame or geopandas.GeoDataFrame if geopandas is installed
            and the responses include coordinates
        """
        df = pd.DataFrame(self.values())

        # Convert datetime columns to datetime objects
        for key, date_format in self.date_formats.items():
            if key in df.columns:
                df[key] = pd.to_datetime(df[key], format=date_format)

        # Convert DataFrame with coordinates to GeoDataFrame if geopandas installed.
        # Uses NAD83 as the CRS. This appears to be NOAA's preferred CRS but it's
        # not explicitly defined in the webservice documentation that I could find.
        if "latitude" in df.columns and "longitude" in df.columns:
            try:
                df = gpd.GeoDataFrame(
                    df,
                    geometry=gpd.points_from_xy(df.longitude, df.latitude),
                    crs="NAD83",
                )
            except NameError:
                # geopandas is optional
                pass

        return df

    @staticmethod
    def _get_results(resp):
        resp_json = resp.json()
        try:
            return resp_json["results"]
        except KeyError:
            return [resp_json]
