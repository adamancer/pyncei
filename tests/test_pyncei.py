import csv
import os

try:
    import geopandas as gpd
    from shapely.geometry import Point
except ImportError:
    pass
import pandas as pd
import pytest

from pyncei import NCEIBot


@pytest.fixture(scope="session")
def output_dir(tmpdir_factory):
    return tmpdir_factory.mktemp("output")


@pytest.fixture()
def ncei():
    with open(os.path.join(os.path.dirname(__file__), "api_token.txt")) as f:
        return NCEIBot(f.read().strip())


@pytest.fixture()
def ncei_cached(output_dir):
    with open(os.path.join(os.path.dirname(__file__), "api_token.txt")) as f:
        return NCEIBot(f.read().strip(), cache_name=output_dir / "cache")


def test_cache(ncei_cached):
    result = ncei_cached.get_stations("COOP:010957")
    cached = ncei_cached.get_stations("COOP:010957")
    assert list(result.values()) == list(cached.values())
    assert not result[0].from_cache
    assert cached[0].from_cache


def test_get_data(ncei):
    ncei.validate_params = True
    response = ncei.get_data(
        datasetid="GHCND",
        stationid=["GHCND:USC00186350"],
        datatypeid=["TMIN", "TMAX"],
        startdate="2015-12-01",
        enddate="2015-12-02",
        sortfield="station",
        sortorder="asc",
        limit=10,
        max=10,
    )
    vals = list(response.values())
    for val in vals:
        del val["url"]
        del val["retrieved"]
    assert vals == [
        {
            "date": "2015-12-01T00:00:00",
            "datatype": "TMAX",
            "station": "GHCND:USC00186350",
            "attributes": ",,7,0800",
            "value": 11.7,
        },
        {
            "date": "2015-12-01T00:00:00",
            "datatype": "TMIN",
            "station": "GHCND:USC00186350",
            "attributes": ",,7,0800",
            "value": 3.3,
        },
        {
            "date": "2015-12-02T00:00:00",
            "datatype": "TMAX",
            "station": "GHCND:USC00186350",
            "attributes": ",,7,0800",
            "value": 15.0,
        },
        {
            "date": "2015-12-02T00:00:00",
            "datatype": "TMIN",
            "station": "GHCND:USC00186350",
            "attributes": ",,7,0800",
            "value": 11.7,
        },
    ]


@pytest.mark.parametrize(
    "params",
    [
        {"locationid": "FIPS:11"},
        {"locationid": "District of Columbia"},
        {"extent": [38.913, -77.114, 38.939, -76.970]},
        {"extent": "38.913,-77.114,38.939,-76.970"},
    ],
)
def test_get_stations(ncei_cached, params):
    kwargs = dict(
        datasetid="GHCND",
        datatypeid=["TMIN", "TMAX"],
        startdate="2015-12-01",
        enddate="2015-12-02",
    )
    kwargs.update(params)
    response = ncei_cached.get_stations(**kwargs)
    vals = list(response.values())
    # Exclude keys likely to change over time
    for val in vals:
        del val["datacoverage"]
        del val["maxdate"]
        del val["retrieved"]
        del val["url"]
    assert vals == [
        {
            "elevation": 45.7,
            "mindate": "1948-08-01",
            "latitude": 38.9385,
            "name": "DALECARLIA RESERVOIR, DC US",
            "id": "GHCND:USC00182325",
            "elevationUnit": "METERS",
            "longitude": -77.1134,
        },
        {
            "elevation": 15.2,
            "mindate": "1948-08-01",
            "latitude": 38.91329,
            "name": "NATIONAL ARBORETUM DC, DC US",
            "id": "GHCND:USC00186350",
            "elevationUnit": "METERS",
            "longitude": -76.97009,
        },
    ]


def test_get_dataset(ncei):
    result = ncei.get_datasets("GHCND").first()
    assert result["id"] == "GHCND"


def test_get_data_category(ncei):
    result = ncei.get_data_categories("TEMP").first()
    assert result["id"] == "TEMP"
    assert result["name"] == "Air Temperature"


def test_get_data_type(ncei):
    result = ncei.get_data_types("TMIN").first()
    assert result["id"] == "TMIN"


def test_get_location(ncei):
    result = ncei.get_locations("CITY:US000001").first()
    assert result["id"] == "CITY:US000001"
    assert result["name"] == "Washington D.C., US"


def test_get_location_category(ncei):
    result = ncei.get_location_categories("ST").first()
    assert result["id"] == "ST"
    assert result["name"] == "State"


def test_get_station(ncei_cached):
    result = ncei_cached.get_stations("COOP:010957").first()
    assert result["id"] == "COOP:010957"
    assert result["name"] == "BOAZ, AL US"


def test_find_ids(ncei):
    result = ncei.find_ids("District of Columbia", "locations")
    assert result == [("locations", "FIPS:11", "District of Columbia")]


def test_find_all(ncei):
    result = ncei.find_ids("temper")
    assert ("datacategories", "ANNTEMP", "Annual Temperature") in result
    assert (
        "datatypes",
        "SX56",
        "Maximum soil temperature with sod cover at 150 cm depth",
    ) in result
    assert ("locations", "ZIP:48182", "Temperance, MI 48182") in result


def test_refresh_lookups(ncei):
    fp = os.path.join(
        os.path.dirname(__file__), "..", "pyncei", "files", "datasets.csv"
    )
    with open(fp) as f:
        content = f.read()
    ncei.refresh_lookups("datasets")
    with open(fp) as f:
        assert f.read() == content


def test_missing_param(ncei):
    ncei.validate_params = True
    with pytest.raises(Exception, match="Required parameters missing"):
        result = ncei.get_data()


def test_invalid_param_name(ncei):
    ncei.validate_params = True
    with pytest.raises(Exception, match="Invalid parameters found"):
        result = ncei.get_data(
            datasetid="GHCND",
            startdate="2015-12-01",
            enddate="2015-12-02",
            bad_param_name="BAD_PARAM_NAME",
        )


def test_invalid_params(ncei):
    ncei.validate_params = True
    with pytest.raises(Exception, match="Parameter errors") as e:
        result = ncei.get_data(
            datasetid=["TOO_MANY_DATASETIDS_1", "TOO_MANY_DATASETIDS_2"],
            stationid=["BAD_STATION_NAME"],
            datatypeid=["BAD_DATETYPE_1", "BAD_DATATYPE_2"],
            startdate="BAD_START_DATE",
            enddate="BAD_END_DATE",
            limit="BAD_LIMIT",
            max="BAD_MAX",
            sortfield="BAD_FIELD_NAME",
            sortorder="BAD_SORT_ORDER",
            units="BAD_UNIT_NAME",
        )


def test_invalid_param_types(ncei):
    ncei.validate_params = True
    with pytest.raises(Exception, match="Parameter errors") as e:
        result = ncei.get_data(
            datasetid=None,
            stationid=None,
            datatypeid=None,
            startdate=None,
            enddate=None,
            limit=None,
            sortfield=None,
            sortorder=None,
            units=None,
        )


def test_to_csv(ncei_cached, output_dir):
    path = output_dir / "test.csv"
    ncei_cached.get_stations("COOP:010957").to_csv(path)
    data = []
    with open(path, encoding="utf-8", newline="") as f:
        rows = csv.reader(f, dialect="excel")
        keys = next(rows)
        for row in rows:
            data.append(dict(zip(keys, row)))
            del data[-1]["retrieved"]
    assert data == [
        {
            "id": "COOP:010957",
            "name": "BOAZ, AL US",
            "latitude": "34.2008",
            "longitude": "-86.1633",
            "elevation": "326.1",
            "elevationUnit": "METERS",
            "datacoverage": "0.9198",
            "mindate": "1938-01-01",
            "maxdate": "2015-11-01",
            "url": "https://www.ncdc.noaa.gov/cdo-web/api/v2/stations/COOP:010957/",
        }
    ]


def test_to_dataframe(ncei_cached):
    df = ncei_cached.get_stations("COOP:010957").to_dataframe()
    expected = {
        "id": {0: "COOP:010957"},
        "name": {0: "BOAZ, AL US"},
        "latitude": {0: 34.2008},
        "longitude": {0: -86.1633},
        "elevation": {0: 326.1},
        "elevationUnit": {0: "METERS"},
        "datacoverage": {0: 0.9198},
        "mindate": {0: pd.Timestamp("1938-01-01 00:00:00")},
        "maxdate": {0: pd.Timestamp("2015-11-01 00:00:00")},
        "url": {0: "https://www.ncdc.noaa.gov/cdo-web/api/v2/stations/COOP:010957/"},
    }
    try:
        assert isinstance(df, gpd.GeoDataFrame)
        expected["geometry"] = {0: Point(-86.1633, 34.2008)}
    except NameError:
        assert isinstance(df, pd.DataFrame)
    dct = df.to_dict()
    del dct["retrieved"]
    assert dct == expected
