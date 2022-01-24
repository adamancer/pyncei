User guide
==========

Install
-------

Install using pip:

    pip install pyncei

Alternatively, you can use the
[environment.yml](https://github.com/adamancer/pyncei/blob/master/environment.yml)
file included in the GitHub repository to build a conda environment and
install pyncei there:

    conda env create -f environment.yml
    conda activate pyncei
    pip install pyncei

This method includes geopandas, which is absent from the pip
installation but if installed allows the
:py:meth:`~pyncei.bot.NCEIResponse.to_dataframe` method to return a
GeoDataFrame when coordinates are provided by NCEI.

Getting started
---------------

To use the NCEI web services, you’ll need a token. The token is a
32-character string provided by NCEI; users can request one
[here](https://www.ncdc.noaa.gov/cdo-web/token). Pass the token to
:py:class:`~pyncei.bot.NCEIBot` to get started:

``` python
from pyncei.reader import NCEIBot

ncei = NCEIBot("ExampleNCEIAPIToken")
```

You can cache queries by using the cache_name parameter when creating an
:py:class:`~pyncei.bot.NCEIBot` object:

``` python
ncei = NCEIBot("ExampleNCEIAPIToken", cache_name="ncei_cache")
```

The cache uses
[CachedSession](https://requests-cache.readthedocs.io/en/stable/session.html#requests_cache.session.CachedSession)
from the requests-cache module. Caching behavior can be modified by
passing keyword arguments accepted by that class to
:py:class:`~pyncei.bot.NCEIBot`. For example, successful requests are
cached indefinitely by default if the cache is being used. Users can
change this behavior using the expire_after keyword argument when
initializing an :py:class:`~pyncei.bot.NCEIBot` object.

:py:class:`~pyncei.bot.NCEIBot` includes methods corresponding to each
of the endpoints described on the CDO website. Query parameters
specified by CDO can be passed as arguments:

``` python
response = ncei.get_data(
      datasetid="GHCND",
      stationid=["GHCND:USC00186350"],
      datatypeid=["TMIN", "TMAX"],
      startdate="2015-12-01",
      enddate="2015-12-02",
  )
```

Each method call may make multiple requests to the API, for example, if
more than 1,000 daily records are requested. Responses are combined in
an :py:class:`~pyncei.bot.NCEIResponse` object, which extends the list
class. *Individual responses* can be accessed using list methods, for
example, by iterating through the object or accessing a single item
using its index. *Data from all responses* can be accessed using the
:py:meth:`~pyncei.bot.NCEIResponse.values` method, which returns an
iterator of dicts, each of which is a single result:

``` python
for val in response.values():
    print(val)
```

The response object includes a
:py:meth:`~pyncei.bot.NCEIResponse.to_csv` method to write results to a
file:

``` python
response.to_csv("station_data.csv")
```

As well as a :py:meth:`~pyncei.bot.NCEIResponse.to_dataframe` method to
write results to a pandas DataFrame (or a geopandas GeoDataFrame if that
module is installed and the results include coordinates):

``` python
df = response.to_dataframe()
```

The table below provides an overview of the available endpoints and
their corresponding methods:

| CDO Endpoint                                                                             | CDO Query Parameter | NCEIBot Method                                         | Values                                                                                                        |
|:-----------------------------------------------------------------------------------------|:--------------------|:-------------------------------------------------------|:--------------------------------------------------------------------------------------------------------------|
| [datasets](http://www.ncdc.noaa.gov/cdo-web/webservices/v2#datasets)                     | datasetid           | :py:meth:`~pyncei.bot.NCEIBot.get_datasets`            | [datasets.csv](https://github.com/adamancer/pyncei/tree/master/pyncei/files/datasets.csv)                     |
| [datacategories](http://www.ncdc.noaa.gov/cdo-web/webservices/v2#dataCategories)         | datacategoryid      | :py:meth:`~pyncei.bot.NCEIBot.get_data_categories`     | [datatypes.csv](https://github.com/adamancer/pyncei/tree/master/pyncei/files/datatypes.csv)                   |
| [datatypes](http://www.ncdc.noaa.gov/cdo-web/webservices/v2#dataTypes)                   | datatypeid          | :py:meth:`~pyncei.bot.NCEIBot.get_data_types`          | [datacategories.csv](https://github.com/adamancer/pyncei/tree/master/pyncei/files/datacategories.csv)         |
| [locationcategories](http://www.ncdc.noaa.gov/cdo-web/webservices/v2#locationCategories) | locationcategoryid  | :py:meth:`~pyncei.bot.NCEIBot.get_location_categories` | [locationcategories.csv](https://github.com/adamancer/pyncei/tree/master/pyncei/files/locationcategories.csv) |
| [locations](http://www.ncdc.noaa.gov/cdo-web/webservices/v2#locations)                   | locationid          | :py:meth:`~pyncei.bot.NCEIBot.get_locations`           | [locations.csv](https://github.com/adamancer/pyncei/tree/master/pyncei/files/locations.csv)                   |
| [stations](http://www.ncdc.noaa.gov/cdo-web/webservices/v2#stations)                     | stationid           | :py:meth:`~pyncei.bot.NCEIBot.get_stations`            | –                                                                                                             |
| [data](http://www.ncdc.noaa.gov/cdo-web/webservices/v2#data)                             | –                   | :py:meth:`~pyncei.bot.NCEIBot.get_data`                | –                                                                                                             |

Each of the NCEIBot get methods accepts either a single positional
argument (used to return data for a single entity) or a series of
keyword arguments (used to search for and retrieve all matching
entities). Unlike CDO, which accepts only ids,
:py:class:`~pyncei.bot.NCEIBot` will try to work with either ids or name
strings. If names are provided, :py:class:`~pyncei.bot.NCEIBot` attempts
to map the name strings to valid ids using
:py:meth:`~pyncei.bot.NCEIBot.find_ids`:

``` python
ncei.find_ids("District of Columbia", "locations")
```

If a unique match cannot be found,
:py:meth:`~pyncei.bot.NCEIBot.find_ids` returns all identifiers that
contain the search term. If you have no idea what data is available or
where to look, you can search across all endpoints by omitting the
endpoint argument:

``` python
ncei.find_ids("temperature")
```

Or you can browse the source files in the Values column of the table
above. The data in these files shouldn’t change much, but they can be
updated using :py:meth:`~pyncei.bot.NCEIBot.refresh_lookups` if
necessary:

``` python
ncei.refresh_lookups()
```

Example: Find and return data from a station
--------------------------------------------

``` python
from datetime import date

from pyncei import NCEIBot, NCEIResponse


# Initialize NCEIBot object using your token string
ncei = NCEIBot("ExampleNCEIAPIToken", cache_name="ncei")

# Set the date range
mindate = date(2016, 1, 1)  # either yyyy-mm-dd or a datetime object
maxdate = date(2019, 12, 31)

# Get all DC stations operating between mindate and maxdate
stations = ncei.get_stations(
    datasetid="GHCND",
    datatypeid=["TMIN", "TMAX"],
    locationid="FIPS:11",
    startdate=mindate,
    enddate=maxdate,
)

# Select the station with the best data coverage
station = sorted(stations.values(), key=lambda s: -int(s["datacoverage"]))[0]

# Get temperature data for the given dates. Note that for the
# data endpoint, you can't request more than one year's worth of daily
# data at a time.
year = maxdate.year
response = NCEIResponse()
while year >= mindate.year:
    response.extend(
        ncei.get_data(
            datasetid=datasetid,
            stationid=station["id"],
            datatypeid=datatypeids,
            startdate=date(year, 1, 1),
            enddate=date(year, 12, 31),
        )
    )
    year -= 1

# Save values to CSV using the to_csv method
response.to_csv(station["id"].replace(":", "") + ".csv")

# Alternatively, merge observation and station data together in a pandas
# DataFrame. If geopandas is installed and coordinates are given, this
# method will return a GeoDataFrame instead.
df_stations = stations.to_dataframe()
df_response = response.to_dataframe()
df_merged = df_stations.merge(df_response, left_on="id", right_on="station")
```
