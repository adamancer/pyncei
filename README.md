pyncei
======

This module provides tools to request data from the [Climate Data Online
webservices](http://www.ncdc.noaa.gov/cdo-web/webservices/v2#gettingStarted)
provided by NOAA's National Centers for Environmental information (formerly
the National Center for Climate Data). Install with:

```
pip install pyncei
```

Documentation for this project is available on
[Read The Docs](http://pyncei.readthedocs.org/en/latest/pyncei.html).

Getting started
---------------

To use the NCEI webservices, you'll need a token. The token is a 32-character
string provided by NCEI; users can request one
[here](https://www.ncdc.noaa.gov/cdo-web/token). Pass the token to
[pyncei.reader.NCEIReader()] to get started:

```python
from pyncei.reader import NCEIReader

token = 'AnExampleTokenFromTheNCEIWebsite'
ncei = NCEIReader(token)
```

The NCEIReader class includes methods corresponding to each of the endpoints
described on the CDO website. Query parameters specified by CDO can be
passed as arguments:

```python
ncei.get_stations(location='FIPS:11')
ncei.get_data(dataset='GHCND',
              station=['COOP:010957'],
              datatype=['TMIN','TMAX'],
              startdate='2015-03-01',
              enddate='2016-03-01')
```

The table below provides a quick overview of the various endpoints and
available parameters:

| CDO Endpoint         | CDO Query Parameter | NCEIReader Method           | NCEIReader Argument | Values                   |
| :------------------- | :------------------ | :-------------------------- | :------------------ | :----------------------- |
| [datasets]           | datasetid           | [get_datasets()]            | dataset             | [datasets.csv]           |
| [datacategories]     | datacategoryid      | [get_data_categories()]     | datatype            | [datatypes.csv]          |
| [datatypes]          | datatypeid          | [get_data_types()]          | datacategory        | [datacategories.csv]     |
| [locationcategories] | locationcategoryid  | [get_location_categories()] | locationcategory    | [locationcategories.csv] |
| [locations]          | locationid          | [get_locations()]           | location            | [locations.csv]          |
| [stations]           | stationid           | [get_stations()]            | station             | --                       |
| [data]               | --                  | [get_data()]                | --                  | --                       |

Each NCEIReader method accepts either a single positional argument (used to
return data for a single id) or a series of keyword arguments.

Note that id fields used by CDO have been renamed. For example, datasetid has
been renamed dataset, and locationid has been renamed location. Unlike CDO,
which accepts only ids, NCEIReader will accept either ids or name strings.
If names are used, NCEIReader attempts to map the name strings to valid id
using [NCEIReader.map_name()], called manually here:

```python
ncei.map_name('District of Columbia', 'locations')
# returns ('FIPS:11', True)
```

When the mapping function fails to find an exact match, it throws an exception
containing a list of similar values that can be used to refine the original
query.

Finding the right term
----------------------

If you have no idea what data is available or where to look, you have a few
options. You can search the terms available for each endpoint using
[NCEIReader.find_in_endpoint()]:

```python
ncei.find_in_endpoint('District of Columbia', 'locations')
# returns ['FIPS:11 => District of Columbia',
#          'FIPS:11001 => District of Columbia County, DC']
```

If the search term is None, this function will return ALL available ids
for the given endpoint. You can search across all endpoints using
[NCEIReader.find_all()]:

```python
ncei.find_all('temperature')
# returns [('datacategories', 'ANNTEMP', 'Annual Temperature'),
#          ('datacategories', 'AUTEMP', 'Autumn Temperature'),...]
```

You can also browse the source files in the Values column of the table
above. The data in these files shouldn't change much, but they can be updated
using [NCEIReader.refresh_lookups()] if necessary:

```python
ncei.refresh_lookups()
```

Queries are cached for one day by default. Users can change this behavior
using the cache parameter when initializing an NCEIReader object. This
parameter specifies the number of seconds pages should persist in the cache;
a value of zero disables the cache entirely.

Example: Find and return data from a station
--------------------------------------------

```python
import csv
from datetime import date

from pyncei import NCEIReader


# Initialize NCEIReader object using your token string
ncei = NCEIReader('AnExampleTokenFromTheNCEIWebsite')
ncei.debug = True  # this flag produces verbose output

# Set the parameters you're looking for. You can use ncei.find_all() or
# ncei_find_in_endpoint() to search the available parameters if you don't
# know what to use.
mindate = '1966-01-01'  # either yyyy-mm-dd or a datetime object
maxdate = '2015-12-31'
datatypes = ['TMIN', 'TMAX']
dataset = 'GHCND'

# You can manually verify parameters if you're so inclined
for datatype in datatypes:
    ncei.map_name(datatype, 'datatypes')

# Get all DC stations operating between mindate and maxdate. The date
# parameters in station queries are a little odd. According to the docs,
# queries will return stations with data from on/before the enddate and
# on/after the startdate. If both parameters are included, the result set
# seems to include all stations that EITHER have data from on/before the
# startdate OR have data on/after the enddate.
stations = ncei.get_stations(location='District of Columbia',
                             dataset=dataset,
                             datatype=datatypes,
                             enddate=mindate)

# Filter out stations no longer operating using maxdate
stations = [station for station in stations
            if station['maxdate'] >= maxdate]

# Find the station with the best data coverage in the result set
stations.sort(key=lambda s:s['datacoverage'], reverse=True)
station = stations[0]
minyear = int(station['mindate'][:4])

# Get temperature data for the the lifetime of the station. Note that for the
# data endpoint, you can't request more than one year's worth of data at a
# time.
year = date.today().year - 1
results = []
while year >= minyear:
    results.extend(ncei.get_data(dataset=dataset,
                                 station=station['id'],
                                 datatype=datatypes,
                                 startdate=date(year, 1, 1),
                                 enddate=date(year, 12, 31)))
    year -= 1

# Write results to csv
fn = station['id'].replace(':', '') + '.csv'
with open(fn, 'wb') as f:
    writer = csv.writer(f, delimiter=',', quotechar='"')
    keys = ('date', 'datatype', 'value')
    writer.writerow(keys)
    for row in results:
        row['date'] = row['date'].split('T')[0].replace('-', '')
        writer.writerow([row[key] for key in keys])

```

[datasets]: http://www.ncdc.noaa.gov/cdo-web/webservices/v2#datasets
[datacategories]: http://www.ncdc.noaa.gov/cdo-web/webservices/v2#dataCategories
[datatypes]: http://www.ncdc.noaa.gov/cdo-web/webservices/v2#dataTypes
[locationcategories]: http://www.ncdc.noaa.gov/cdo-web/webservices/v2#locationCategories
[locations]: http://www.ncdc.noaa.gov/cdo-web/webservices/v2#locations
[stations]: http://www.ncdc.noaa.gov/cdo-web/webservices/v2#stations
[data]: http://www.ncdc.noaa.gov/cdo-web/webservices/v2#data

[pyncei.reader.NCEIReader()]: http://pyncei.readthedocs.org/en/latest/pyncei.html#pyncei.reader.NCEIReader
[NCEIReader.find_all()]: http://pyncei.readthedocs.org/en/latest/pyncei.html#pyncei.reader.NCEIReader.find_all
[NCEIReader.find_in_endpoint()]: http://pyncei.readthedocs.org/en/latest/pyncei.html#pyncei.reader.NCEIReader.find_in_endpoint
[NCEIReader.map_name()]: http://pyncei.readthedocs.org/en/latest/pyncei.html#pyncei.reader.NCEIReader.map_name
[NCEIReader.refresh_lookups()]: http://pyncei.readthedocs.org/en/latest/pyncei.html#pyncei.reader.NCEIReader.refresh_lookups

[get_data()]: http://pyncei.readthedocs.org/en/latest/pyncei.html#pyncei.reader.NCEIReader.get_data
[get_datasets()]: http://pyncei.readthedocs.org/en/latest/pyncei.html#pyncei.reader.NCEIReader.get_datasets
[get_data_types()]: http://pyncei.readthedocs.org/en/latest/pyncei.html#pyncei.reader.NCEIReader.get_data_types
[get_data_categories()]: http://pyncei.readthedocs.org/en/latest/pyncei.html#pyncei.reader.NCEIReader.get_data_categories
[get_locations()]: http://pyncei.readthedocs.org/en/latest/pyncei.html#pyncei.reader.NCEIReader.get_locations
[get_location_categories()]: http://pyncei.readthedocs.org/en/latest/pyncei.html#pyncei.reader.NCEIReader.get_location_categories
[get_stations()]: http://pyncei.readthedocs.org/en/latest/pyncei.html#pyncei.reader.NCEIReader.get_stations

[datacategories.csv]: https://github.com/adamancer/pyncei/tree/master/pyncei/files/datacategories.csv
[datasets.csv]: https://github.com/adamancer/pyncei/tree/master/pyncei/files/datasets.csv
[datatypes.csv]: https://github.com/adamancer/pyncei/tree/master/pyncei/files/datatypes.csv
[locationcategories.csv]: https://github.com/adamancer/pyncei/tree/master/pyncei/files/locationcategories.csv
[locations.csv]: https://github.com/adamancer/pyncei/tree/master/pyncei/files/locations.csv
