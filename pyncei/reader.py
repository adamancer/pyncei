"""Python bindings for the Climate Data Online webservices provided by NOAA's
National Centers for Environmental information (formerly the National Center
for Climate Data). Install with :code:`pip install pyncei`."""

import csv
import glob
import json
import math
import os
import pprint
import textwrap
import time
from copy import copy
from datetime import datetime, timedelta

import requests
import requests_cache
from lxml import etree


class NCEIReader(object):
    """Contains functions to request data from the NCEI webservices

    Attributes:
        cache (int): Time in seconds to cache requests. If 0, requests
            are not cached.
        endpoints (list): List of available endpoints
        token (str): NCEI token
        wait (float): Time in seconds between requests. NCEI
            allows a maximum of five queries per second.

    The get functions described below use a common set of keyword arguments.
    The sortorder, limit, offset, count, and max arguments can be used in
    any get function; other keywords vary by endpoint. Most values appear to
    be case-sensitive. Query validation done by this class should capture
    most but not all case errors.

    Args:
        dataset (str or list): the id or name of a NCEI dataset. Multiple
            values allowed for most functions. Examples: GHCND; PRECIP_HLY;
            Weather Radar (Level III). Corresponds to the datasetid field
            in NCEI data model.
        datacategory (str or list): the id or name of a NCEI data category.
            Data categories are broader than data types. Multiple values
            allowed. Examples: TEMP, WXTYPE, Degree Days. Corresponds to the
            datacategoryid field in the NCEI data model.
        datatype (str or list): the id or name of a data type. Multiple values
            allowed. Examples: TMIN; SNOW; Long-term averages of fall growing
            degree days with base 70F. Corresponds to the datatypeid field in
            the NCEI data model.
        location (str or list): the id or name of a location. Multiple values
            allowed. Examples: Maryland; FIPS:24; ZIP:20003; London, UK.
            Corresponds to the locationid field in NCEI data model.
        station (str or list): the id of name of a station in the NCEI
            database. Multiple values allowed. Examples: COOP:010957.
            Corresponds to the stationid field in NCEI data model.
        startdate (str or datetime): the earliest date retrieved or available
        enddate (str or datetime): the latest date retrieved or available
        sortfield (str): field by which to sort the query results. Available
            sort fields vary by endpoint.
        sortorder (str): specifies whether sort is ascending or descending.
            Must be 'asc' or 'desc'.
        limit (int): number of records to return per query
        offset (int): index of the first record to return
        count (bool): if present, query returns total number of records
        max (int): maximum number of records to return
    """


    def __init__(self, token, wait=0.2, cache=86400):
        """Initialize NCEIReader object

        Args:
            token (str): NCEI token
            wait (float or int):
            cache (int): time in seconds to cache requests. If 0, requests
                are not cached.

        Returns:
            None
        """
        self.debug = False

        # Queries are capped at five per second, so enforce that with
        # a minimum wait time of 0.2 seconds
        if wait < 0.2:
            self.wait = 0.2
        else:
            self.wait = wait
        if cache:
            self.cache = True
            requests_cache.install_cache('ncei', expires_after=cache)
        else:
            self.cache = False

        # Set up requests session using NCDI token
        self.s = requests.Session()
        self.s.headers.update({'token': token, 'User-Agent': 'pyncei/0.1'})

        self._validators = {
            'count': bool,
            'datacategory': self._check_name,
            'dataset': self._check_name,
            'datatype': self._check_name,
            'enddate': self._check_date,
            'extent': self._check_extent,
            'limit': self._check_limit,
            'location': self._check_name,
            'locationcategory': self._check_name,
            'max': self._check_positive_integer,
            'offset': self._check_positive_integer,
            'station': self._check_name,
            'startdate': self._check_date,
            'sortfield': self._check_sortfield,
            'sortorder': self._check_sortorder
            }

        # List of fields that can occur more than once in a given query.
        # This list may need to be adjusted depending on the endpoint;
        # for example, the data endpoint allows only one dataset to be passed.
        self._allow_multiple = [
            'datacategory',
            'dataset',
            'datatype',
            'location',
            'locationcategory',
            'station'
        ]

        # List of endpoints
        self.endpoints = [
            'datacategories',
            'datasets',
            'datatypes',
            'locations',
            'locationcategories',
            'stations'
        ]

        # Create name lookups to help users map to ids needed for querying
        self._lookups = {}
        self._filepath = os.path.join(os.path.dirname(__file__), 'files')
        try:
            os.makedirs(self._filepath)
        except OSError:
            for fp in glob.iglob(os.path.join(self._filepath, '*.csv')):
                fn = os.path.splitext(os.path.basename(fp))[0]
                self._lookups[fn] = {}
                with open(fp, 'rb') as f:
                    rows = csv.reader(f, delimiter=',', quotechar='"')
                    try:
                        rows.next()
                    except StopIteration:
                        pass
                    else:
                        for row in rows:
                            row = tuple(row)
                            for key in row:
                                self._lookups[fn][key.lower()] = row

        # Constants
        self.EXTENT_CONTINENTAL_US = '24.5000,-125.0000,49.5000,-67.0000'


    def get_data(self, **kwargs):
        """Retrieves historical climate data matching the given parameters

        See :py:func:`~pyncei.NCEIReader.NCEIReader` for more details about
        each keyword argument.

        Args:
            dataset (str): Required. Only one value allowed.
            startdate (str or datetime): Required. Returned stations will
                have data for the specified dataset/type from on or after
                this date.
            enddate (str or datetime): Required. Returned stations will
                have data for the specified dataset/type from on or before
                this date.
            datatype (str or list): Optional
            location (str or list): Optional
            station (str or list): Optional
            sortfield (str): Optional. If provided, must be one of 'datatype',
                'date', or 'station'.

        Returns:
            List of dicts containing historical weather data
        """
        url = 'http://www.ncdc.noaa.gov/cdo-web/api/v2/data'
        required = ['dataset',
                    'startdate',
                    'enddate']
        optional = ['datatype',
                    'location',
                    'station',
                    'sortfield',
                    'sortorder',
                    'limit',
                    'offset',
                    'includemetadata']
        self._allow_multiple.remove('dataset')
        url, params = self._prepare_query(url, [], kwargs, required, optional)
        self._allow_multiple.append('dataset')
        return self._get(url, params)


    def get_datasets(self, *args, **kwargs):
        """Returns data from the NCEI dataset endpoint

        Pass a dataset id as a positional argument to get data about that
        category. See :py:func:`~pyncei.NCEIReader.NCEIReader` for more
        details about each keyword argument.

        Args:
            datatype (str or list): Optional
            location (str or list): Optional
            station (str or list): Optional
            sortfield (str): Optional. If provided, must be one of 'id',
                'name', 'mindate', 'maxdate', or 'datacoverage'.

        Returns:
            List of dicts containing metadata for all matching datasets
        """
        url = 'http://www.ncdc.noaa.gov/cdo-web/api/v2/datasets'
        required = []
        optional = ['datatype',
                    'location',
                    'station',
                    'startdate',
                    'enddate',
                    'sortfield',
                    'sortorder',
                    'limit',
                    'offset']
        url, params = self._prepare_query(url, args, kwargs, required, optional)
        if 'count' in params:
            return self._count(url, params)
        else:
            return self._get(url, params)


    def get_data_categories(self, *args, **kwargs):
        """Returns code and labels for NCDI data categories

        Pass a data category id as a positional argument to get data about
        that category. See :py:func:`~pyncei.NCEIReader.NCEIReader` for more
        details about each keyword argument.

        Args:
            dataset (str or list): Optional
            location (str or list): Optional
            station (str or list): Optional
            startdate (str or datetime): Optional
            enddate (str or datetime): Optional
            sortfield (str): Optional. If provided, must be one of 'id',
                'name', 'mindate', 'maxdate', or 'datacoverage'.

        Returns:
            List of dicts containing metadata for all matching data
            categories
        """
        url = 'http://www.ncdc.noaa.gov/cdo-web/api/v2/datacategories'
        required = []
        optional = ['dataset',
                    'location',
                    'station',
                    'startdate',
                    'enddate',
                    'sortfield',
                    'sortorder',
                    'limit',
                    'offset']
        url, params = self._prepare_query(url, args, kwargs, required, optional)
        if 'count' in params:
            return self._count(url, params)
        else:
            return self._get(url, params)


    def get_data_types(self, *args, **kwargs):
        """Returns information about NCEI data categories

        Pass a datatype id as a positional argument to get data about that
        datatype. See :py:func:`~pyncei.NCEIReader.NCEIReader` for more
        details about each keyword argument.

        Args:
            dataset (str or list): Optional
            location (str or list): Optional
            station (str or list): Optional
            datacategory (str or list): Optional
            startdate (str or datetime): Optional
            enddate (str or datetime): Optional
            sortfield (str): Optional. If provided, must be one of 'id',
                'name', 'mindate', 'maxdate', or 'datacoverage'.

        Returns:
            List of dicts containing metadata for all matching data types
        """
        url = 'http://www.ncdc.noaa.gov/cdo-web/api/v2/datatypes'
        required = []
        optional = ['dataset',
                    'location',
                    'station',
                    'datacategory',
                    'startdate',
                    'enddate',
                    'sortfield',
                    'sortorder',
                    'limit',
                    'offset']
        url, params = self._prepare_query(url, args, kwargs, required, optional)
        if 'count' in params:
            return self._count(url, params)
        else:
            return self._get(url, params)


    def get_location_categories(self, *args, **kwargs):
        """Returns information about NCEI location categories

        Pass a location category id as a positional argument to get data about
        that category. See :py:func:`~pyncei.NCEIReader.NCEIReader` for more
        details about each keyword argument.

        Args:
            dataset (str or list): Optional
            sortfield (str): Optional. If provided, must be one of 'id' or
                'name'.

        Returns:
            List of dicts containing metadata about location categories
        """
        url = 'http://www.ncdc.noaa.gov/cdo-web/api/v2/locationcategories'
        required = []
        optional = ['dataset',
                    'startdate',
                    'enddate',
                    'sortfield',
                    'sortorder',
                    'limit',
                    'offset']
        url, params = self._prepare_query(url, args, kwargs, required, optional)
        if 'count' in params:
            return self._count(url, params)
        else:
            return self._get(url, params)


    def get_locations(self, *args, **kwargs):
        """Returns metadata for locations matching the given parameters

        Pass a location id as a positional argument to get data about that
        location. See :py:func:`~pyncei.NCEIReader.NCEIReader` for more details
        about each keyword argument.

        Args:
            dataset (str or list): Optional
            locationcategory (str or list): Optional
            datacategory (str or list): Optional
            sortfield (str): Optional. If provided, must be one of 'id',
                'name', 'mindate', 'maxdate', or 'datacoverage'.

        Returns:
            List of dicts containing metadata for all matching locations
        """
        url = 'http://www.ncdc.noaa.gov/cdo-web/api/v2/locations'
        required = []
        optional = ['dataset',
                    'locationcategory',
                    'datacategory',
                    'startdate',
                    'enddate',
                    'sortfield',
                    'sortorder',
                    'limit',
                    'offset']
        url, params = self._prepare_query(url, args, kwargs, required, optional)
        if 'count' in params:
            return self._count(url, params)
        else:
            return self._get(url, params)


    def get_stations(self, *args, **kwargs):
        """Returns metadata for stations matching the given parameters

        Pass a station id as a positional argument to get data about that
        station. See :py:func:`~pyncei.NCEIReader.NCEIReader` for more details
        about each keyword argument.

        Args:
            dataset (str or list): Optional
            location (str or list): Optional
            datacategory (str or list): Optional
            datatype (str or list): Optional
            extent (str): Optional
            sortfield (str): Optional. If provided, must be one of 'id',
                'name', 'mindate', 'maxdate', or 'datacoverage'.

        Returns:
            List of dicts containing metadata for all matching stations
        """
        url = 'http://www.ncdc.noaa.gov/cdo-web/api/v2/stations'
        required = []
        optional = ['dataset',
                    'location',
                    'datacategory',
                    'datatype',
                    'extent',
                    'startdate',
                    'enddate',
                    'sortfield',
                    'sortorder',
                    'limit',
                    'offset']
        url, params = self._prepare_query(url, args, kwargs, required, optional)
        if 'count' in params:
            return self._count(url, params)
        else:
            return self._get(url, params)


    def get_dataset(self, datasetid):
        """Convenience function to return metadata for a single station

        Equivalent to :code:`NCEIReader.get_stations(station)[0]`.

        Args:
            datasetid (str): NCDI dataset id

        Returns:
            Dict containing station metadata, if found.
        """
        try:
            return self.get_datasets(datasetid)[0]
        except IndexError:
            return {}


    def get_data_category(self, datacategoryid):
        """Convenience function to return metadata for a single data category

        Equivalent to :code:`NCEIReader.get_data_categories(datacategoryid)[0]`.

        Args:
            datacategoryid (str): NCDI data category id

        Returns:
            Dict containing station metadata, if found.
        """
        try:
            return self.get_data_categories(datacategoryid)[0]
        except IndexError:
            return {}


    def get_data_type(self, datatypeid):
        """Convenience function to return metadata for a single data type

        Equivalent to :code:`NCEIReader.get_data_types(datatypeid)[0]`.

        Args:
            datatypeid (str): NCDI datatype id

        Returns:
            Dict containing data type metadata, if found.
        """
        try:
            return self.get_data_types(datatypeid)[0]
        except IndexError:
            return {}


    def get_location_category(self, locationcategoryid):
        """Convenience function to return metadata for one location category

        Equivalent to
        :code:`NCEIReader.get_location_categories(locationcategoryid)[0]`.

        Args:
            locationcategoryid (str): NCDI location category id

        Returns:
            Dict containing location category metadata, if found.
        """
        try:
            return self.get_location_categories(locationcategoryid)[0]
        except IndexError:
            return {}


    def get_location(self, locationid):
        """Convenience function to return metadata for a single location

        Equivalent to :code:`NCEIReader.get_locations(locationid)[0]`.

        Args:
            locationid (str): NCDI location id

        Returns:
            Dict containing location metadata, if found.
        """
        try:
            return self.get_locations(locationid)[0]
        except IndexError:
            return {}


    def get_station(self, stationid):
        """Convenience function to return metadata for a single station

        Equivalent to :code:`NCEIReader.get_stations(stationid)[0]`.

        Args:
            station (str): station id

        Returns:
            Dict containing station metadata, if found.
        """
        try:
            return self.get_stations(stationid)[0]
        except IndexError:
            return {}


    def get_endpoint(self, key):
        """Get the name of the NCEI endpoint corresponding to a given key

        Args:
            key (str): parameter name (for example, dataset or datasetid)

        Returns:
            Name of corresponding NCEI endpoint, or None if invalid key
        """
        if key.endswith('id'):
            key = key[:-2]
        if key.endswith('y'):
            key = key[:-1] + 'ies'
        elif not key.endswith('s'):
            key += 's'
        if key in self.endpoints:
            return key


    def find_all(self, search):
        """Find key terms matching a search string across all endpoints

        Args:
            search (str): search string

        Returns:
            List of (endpoint, id, name) for matching key terms from all
            endpoints
        """
        results = []
        for endpoint in sorted(self._lookups.keys()):
            results.extend(self.find_in_endpoint(search, endpoint))
        return results


    def find_in_endpoint(self, search, endpoint):
        """Find key terms that match the search string for a given endpoint

        Args:
            search (str): a search string used to filter the results. If None,
                the function will return a list of all terms for the endpoint.
            endpoint (str): the name of an NCEI endpoint

        Returns:
            List of (endpoint, id, name) for matching key terms from the
            specified endpoint
        """
        try:
            results = self._lookups[endpoint.lower()]
        except KeyError:
            results = []
        else:
            if search is not None:
                s = search.lower()
                results = [results[key] for key in results if s in key]
            else:
                results = results.values()
        return sorted(list(set((endpoint, row[0], row[1]) for row in results)))


    def map_name(self, value, endpoint):
        """Map name string to id for an endpoint

        Args:
            value (str): id or name of an item expected in a given enpoint
            endpoint (str): the name of an NCEI endpoint

        Returns:
            Tuple of (id, True) if exact match found, or (error message, False)
            if not.
        """
        orig_value = copy(value)
        value = value.lower()
        try:
            value = self._lookups[endpoint][value.lower()][0]
        except KeyError:
            msg = '{} not found in {}'.format(orig_value, endpoint)
            try:
                self._lookups[endpoint]
            except KeyError:
                self.pprint(u'**Warning: {} not checked. No lookup configured'
                             ' for {} endpoint**'.format(orig_value, endpoint))
                return orig_value, True
            else:
                value = value.split(' ')
                sw = value[0]
                ew = value.pop()
                keys = []
                [keys.append(' ' + ' => '.join(self._lookups[endpoint][k]))
                 for k in self._lookups[endpoint]
                 if k.startswith(sw) or k.endswith(ew)]
                keys = sorted(set(keys))[:10]
                if len(keys):
                    msg += '. Found similar: \n{}'.format('\n'.join(keys))
                raise Exception(msg)
        if value.lower() != orig_value.lower():
            self.pprint(u'{} mapped to {}!'.format(orig_value, value),
                        self.debug)
        return value, True


    def refresh_lookups(self, keys=None):
        """Update the csv files used to populate the lookup table

        Args:
            keys (list): list of endpoints to populate. If empty,
                everything but stations will be populated.

        Returns:
            None
        """
        endpoints = {
            'datasets': self.get_datasets,
            'datacategories': self.get_data_categories,
            'datatypes': self.get_data_types,
            'locationcategories': self.get_location_categories,
            'locations': self.get_locations,
            'stations': self.get_stations,
        }
        # Remove existing lookup files
        for fp in glob.iglob(os.path.join(self._filepath, '*.csv')):
            os.remove(fp)
        if keys is None:
            keys = endpoints.keys()
            try:
                keys.remove('stations')
            except ValueError:
                pass
        elif not isinstance(keys, list):
            keys = [keys]
        for key in keys:
            try:
                results = endpoints[key]()
            except KeyError:
                raise Exception('{} is not a valid id'.format(key))
            else:
                fp = os.path.join(self._filepath, key + '.csv')
                with open(fp, 'wb') as f:
                    writer = csv.writer(f, delimiter=',', quotechar='"')
                    writer.writerow(['id', 'name'])
                    for result in results:
                        row = [result['id'], result['name']]
                        writer.writerow(row)


    def pprint(self, s, flag=True, indent=0):
        """Pretty prints strings, lists, and dicts

        Args:
            s (str, dict, or list): object to print
            flag (bool): controls whether to print
            indent (int): number of spaces by which to indent

        Returns:
            None
        """
        if flag:
            if isinstance(s, (list, dict)):
                pprint.PrettyPrinter().pprint(s)
            else:
                print textwrap.fill(s, initial_indent=' ' * indent,
                                    subsequent_indent=' ' * (indent+1))



    def _count(self, url, params):
        """Finds the number of records matching a url and parameter set

        Args:
            url (str): NCDI webservice url
            params (dict): query parameters

        Returns:
            List of dicts containing the requested data
        """
        r = self.s.get(url, params=params)
        if r.status_code == 200:
            return json.loads(r.text)['metadata']['resultset']['count']
        msg = (u'Failed to retrieve {}'
                ' ({} status): {}').format(r.url, r.status_code, r.text)
        raise Exception(msg)


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
        if not url.endswith('/'):
            try:
                offset = params['offset']
            except KeyError:
                params['offset'] = offset = 1
            else:
                # Offsets 0 and 1 both return the same record. Specifying
                # an offset of 1 makes subsequent offsets (made by adding
                # the limit to the last offset) start at the right record.
                if offset is 0:
                    params['offset'] = offset = 1
            # Minimize number of queries required to retrieve data
            # by adjusting limit based on total number of records
            try:
                limit = params['limit']
            except KeyError:
                params['limit'] = limit = 1000
            try:
                total = params.pop('max')
            except KeyError:
                total = 10**12  # any very large number will do here
            else:
                if total < 1000 :
                    params['limit'] = limit = total
        else:
            total = limit = 1
        if self.debug:
            self.pprint(u'Final parameter set:', self.debug, 2)
            if total > 0:
                self.pprint(u'total: {}'.format(total), self.debug, 4)
            for key in params:
                self.pprint(u'{}: {}'.format(key, params[key]), self.debug, 4)
        results = []
        while len(results) < total:
            self.pprint(u'Requesting data...', self.debug, 2)
            r = self.s.get(url, params=params)
            self.pprint(u'Retrieved {}'.format(r.url), self.debug, 2)
            if r.status_code == 200:
                # Enforce a wait period between requests
                if self.cache and not r.from_cache:
                    self.pprint(u'Caching request...'.format(r.url),
                                self.debug, 2)
                    time.sleep(self.wait)
                elif not self.cache:
                    self.pprint(u'Waiting {} seconds...'.format(self.wait),
                                self.debug, 2)
                    time.sleep(self.wait)
                else:
                    self.pprint(u'URL was retrieved from cache'.format(r.url),
                                self.debug, 2)
                self.pprint(u'Parsing data...', self.debug, 2)
                data = json.loads(r.text)
                if not len(data):
                    self.pprint(u'No data found!', self.debug, 2)
                    return []
                # Check for total number of records
                if not total == limit == 1:
                    try:
                        rcount
                    except UnboundLocalError:
                        try:
                            rcount = data['metadata']['resultset']['count']
                        except KeyError:
                            msg = (u'Could not parse response from'
                                    ' {}: {}').format(r.url, r.text)
                            raise Exception(msg)
                        else:
                            msg = (u'{:,} total records match these'
                                    ' parameters!').format(rcount)
                            self.pprint(msg, self.debug, 2)
                            if rcount < total:
                                total = rcount
                            params['includemetadata'] = False
                try:
                    results.extend(data['results'])
                except KeyError:
                    results = [data]
                else:
                    params['offset'] += limit
                msg = u'{:,}/{:,} records retrieved!'.format(len(results),
                                                             total)
                self.pprint(msg, self.debug, 2)
            else:
                msg = (u'Failed to retrieve {}'
                        ' ({} status): {}').format(r.url, r.status_code, r.text)
                raise Exception(msg)
        return results


    def _prepare_query(self, url, args, kwargs, required, optional):
        """Validate query

        Args:
            url (str): url to NCEI endpoint
            args (tuple): string that specifies a single result for
                a given endpoint
            kwargs (dict): keyed query parameters
            required (list): required fields for endpoint
            optional (list): optional fields for endpoint

        Returns:
            Tuple (url string, paramter dict) if query is valid
        """
        self.pprint(u'Preparing request to {}...'.format(url), self.debug, 0)
        try:
            url += '/' + args[0] + '/'
        except IndexError:
            # Confirm that all required fields are present
            missing = [key for key in required if not key in kwargs]
            if len(missing):
                e = ', '.join(missing)
                raise Exception('Required parameters missing: {}'.format(e))
            self.pprint('No required parameters missing!', self.debug, 2)
            # Extend optional with helper fields
            optional.extend(['count', 'max'])
            # Check that all fields in kwargs are valid
            invalid = [key for key in kwargs if not key in required + optional]
            if len(invalid):
                e = ', '.join(invalid)
                raise Exception('Invalid parameters found: {}'.format(e))
            self.pprint('No invalid parameters found!', self.debug, 2)
            # Clean up kwargs
            params = self._check_kwargs(kwargs, url.split('/').pop())
            # Query string endpoint
            return url, params
        else:
            # Specific endpoint
            return url, {}


    def _check_kwargs(self, kwargs, endpoint):
        """Validate values given for query parameters

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
            if isinstance(vals, list) and not key in self._allow_multiple:
                raise Exception('{} only accepts one value in the'
                                ' {} endpoint'.format(key, endpoint))
            elif not isinstance(vals, list):
                vals =[vals]
            validated = []
            for val in vals:
                try:
                    value, status = self._validators[key](val, key, endpoint)
                except KeyError:
                    # Catches bad parameter names. In practice, this should
                    # never occur because bad params should be weeded out
                    # beforehand.
                    raise Exception('{} is not a valid parameter'.format(key))
                else:
                    if status is False:
                        errors.append(value)
                    else:
                        validated.append(value)
                        self.pprint(u' {}: {} is valid!'.format(key, value),
                                    self.debug, 2)
            if not key in self._allow_multiple:
                if len(validated) > 1:
                    raise Exception('{} only accepts one value'.format(key))
                validated = validated[0]
            # Map helper fields to corresponding query fields
            try:
                self.endpoints.index(self.get_endpoint(key))
            except ValueError:
                kwargs[key] = validated
            else:
                kwargs[key + 'id'] = validated
                del kwargs[key]
        # Final coherence check
        # This condition is not true for data requests!
        #try:
        #
        #     if kwargs['startdate'] >= kwargs['enddate']:
        #         errors.append('startdate should be earlier than enddate')
        #except KeyError:
        #    pass
        if len(errors):
            s = ': ' if len(errors) == 1 else 's: \n'
            msg = u'Parameter error{}{}'.format(s, '\n'.join(errors))
            raise Exception(msg)
        return kwargs


    def _check_name(self, value, key, endpoint):
        """Map name to id for a given key, if possible

        Args:
            value (str): date or equivalent
            key (str): identity of field being checked
            endpoint (str): name of current NCEI endpoint

        Returns:
            Tuple (id, True) if name is valid, or tuple
            (error message, False) if not.
        """
        # Convert key to appropriate endpoint
        if key.endswith('y'):
            key = key[:-1] + 'ies'
        elif not key.endswith('s'):
            key += 's'
        try:
            _id, status = self.map_name(value, key)
        except KeyError:
            self.pprint('No lookup list found for {}'.format(key),
                        self.debug, 2)
            return value, True
        else:
            if status:
                return _id, status


    def _check_date(self, date, key, endpoint):
        """Validate and formate date

        Args:
            date (str or dateime.datetime): date or equivalent
            key (str): identity of field being checked
            endpoint (str): name of current NCEI endpoint

        Returns:
            Tuple (date string, True) if date is valid, or tuple
            (error message, False) if not.
        """
        try:
            return date.strftime('%Y-%m-%d'), True
        except AttributeError:
            try:
                datetime.strptime(date, '%Y-%m-%d')
            except TypeError:
                pass
            else:
                return date, True
        msg = u'Must be datetime object or string formatted as %Y-%m-%d'
        return msg, False


    def _check_extent(self, key, extent, endpoint):
        """Validate sortfield query parameter

        Args:
            extent (str): comma-delimited bounding box of form
                'min_lat, min_lng, max_lat, max_lng'
            key (str): identity of field being checked
            endpoint (str): name of current NCEI endpoint

        Returns:
            Tuple (extent string, True) if extent is valid, or tuple
            (error message, False) if not.
        """
        coordinates = [s.strip() for s in extent.split(',')]
        if (float(coordinates[0]) < float(coordinates[2])
            and float(coordinates[1]) < float(coordinates[3])):
            return ','.join(coordinates), True
        msg = u'Must be a string as "min_lat, min_lng, max_lat, max_lng"'
        return msg, False


    def _check_sortfield(self, value, key, endpoint):
        """Validate sortfield query parameter

        Args:
            value (str): name of sort field. Sort fields vary by endpoint.
            key (str): identity of field being checked
            endpoint (str): name of current NCEI endpoint

        Returns:
            Tuple (sort field, True) if sort field is valid, or tuple
            (error message, False) if not.
        """
        fields = {
            'data': ['datatype', 'date', 'station'],
            'datasets': ['id', 'name', 'mindate', 'maxdate', 'datacoverage'],
            'datacategories': ['id', 'name'],
            'locationcategories': ['id', 'name'],
            'locations': ['id', 'name', 'mindate', 'maxdate', 'datacoverage'],
            'stations': ['id', 'name', 'mindate', 'maxdate', 'datacoverage'],
        }
        try:
            value = value.lower()
        except AttributeError:
            pass
        else:
            if value in fields[endpoint]:
                return value, True
        msg = u'Must be one of the following: {}'.format(', '.join(valid))
        return msg, False


    def _check_sortorder(self, value, key, endpoint):
        """Validate sort order

        Args:
            value (str): 'asc' or 'desc'
            key (str): identity of field being checked
            endpoint (str): name of current NCEI endpoint

        Returns:
            Tuple (validated string, True) if order is valid, or tuple
            (error message, False) if not.
        """
        valid = ['asc', 'desc']
        try:
            value = value.lower()
        except AttributeError:
            pass
        else:
            if value in valid:
                return value, True
        msg = u'Must be one of the following: {}'.format(', '.join(valid))
        return msg, False


    def _check_limit(self, value, key, endpoint):
        """Validate limit

        Args:
            value (str or int): integer to validate
            key (str): identity of field being checked
            endpoint (str): name of current NCEI endpoint

        Returns:
            Tuple (validated integer, True) if limit is valid, or tuple
            (error message, False) if not.
        """
        try:
            value = int(value)
        except TypeError:
            pass
        else:
            if 0 < value <= 1000:
                return value, True
        msg = u'Must be an integer between 1 and 1000, inclusive'
        return msg, False


    def _check_positive_integer(self, value, key, endpoint):
        """Validate positive integer

        Args:
            value (str or int): integer to validate
            key (str): identity of field being checked
            endpoint (str): name of current NCEI endpoint

        Returns:
            Tuple (validated integer, True) if number is valid, or tuple
            (error message, False) if not.
        """
        try:
            value = int(value)
        except TypeError:
            pass
        else:
            if value >= 0:
                return value, True
        msg = u'Must be an integer greater than or equal to 0'
        return msg, False
