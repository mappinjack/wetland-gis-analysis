import json
import sys
import os
import base64
import boto3
import io

os.environ["GDAL_DATA"] = "/opt/share/gdal"
os.environ["PROJ_LIB"] = "/opt/share/proj"

import numpy as np

from osgeo import gdal, osr
from osgeo.gdalnumeric import *
from osgeo.gdalconst import *


s3_client = boto3.client("s3")
gdal.AllRegister()
RASTERS = {"hydric": "WetlandExtent", "land": "LandCover", "water": "OverlandFlow", "saturation": "SaturationIndex", "wetland": "WetlandDistance"}

def lambda_handler(event, context):
    weights = event["body"]
    if not isinstance(weights, dict):
        weights = json.loads(weights)
    print(f"Weights: {weighs}")
    loadRasters("rasters3/")
    NDV, xsize, ysize, GeoT, Projection, DataType = getGeoInfo("WetlandExtent")

    overlayArray = numpy.zeros((ysize, xsize), numpy.float64)

    for nickname, raster_name in RASTERS.items():
        weight = weights[nickname] / 100.0 # Percent to proportion
        raster = gdal.Open(f"/vsimem/{raster_name}.tif")
        rasterArray = raster.GetRasterBand(1).ReadAsArray(0, 0, xsize, ysize)
        rasterArray = np.where(rasterArray is None or rasterArray > 10, 0, rasterArray)
        weightedArray = rasterArray * weight
        # TODO add masks
        overlayArray = np.add(overlayArray, weightedArray)

    print(overlayArray)

    # colors = gdal.ColorTable()
    # colors.CreateColorRamp(0, (229, 245, 249), 1, (153, 216, 201))
    # colors.CreateColorRamp(2, (153, 216, 201), 3, (44, 162, 95))
    # outDs.GetRasterBand(1).SetRasterColorTable(colors)
    # outDs.GetRasterBand(1).SetRasterColorInterpretation(gdal.GCI_PaletteIndex)

    # Set up the GTiff driver
    driver = gdal.GetDriverByName("GTiff")

    print(f"Projection: {Projection}")
    # Now turn the array into a GTiff.
    newFileName = createGeoTiff(
        "output", overlayArray, driver, NDV, xsize, ysize, GeoT, Projection, DataType
    )

    outputKey = writeRasterToS3(newFileName)

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "corsUrl": f"https://cors-anywhere.herokuapp.com/https://mappinjack-public.s3.ca-central-1.amazonaws.com/{outputKey}",
                "downloadUrl": f"https://mappinjack-public.s3.ca-central-1.amazonaws.com/{outputKey}"
            }
        ),
        "headers": {"Access-Control-Allow-Origin": "*", "Content-Type": "application/json"},
    }
    # Follow: https://gis.stackexchange.com/questions/57005/python-gdal-write-new-raster-using-projection-from-old

def writeRasterToS3(input_raster="output", output_key="new"):
    if "vsimem" not in input_raster:
        input_raster = f"/vsimem/{input_raster.replace('.tif', '')}.tif"
    output_key = f"{output_key.replace('.tif', '')}.tif"

    f = gdal.VSIFOpenL(input_raster, "rb")
    gdal.VSIFSeekL(f, 0, 2)  # seek to end
    size = gdal.VSIFTellL(f)
    gdal.VSIFSeekL(f, 0, 0)  # seek to beginning
    data = gdal.VSIFReadL(1, size, f)
    gdal.VSIFCloseL(f)

    #TODO apply color table?

    s3_client.put_object(Body=data, Bucket="mappinjack-public", Key=output_key)
    s3 = boto3.resource("s3")
    object_acl = s3.ObjectAcl("mappinjack-public", output_key)
    object_acl.put(ACL="public-read")

    return output_key


def loadRasters(keyPath):
    for raster_name in RASTERS.values():
        raster_path = f"{keyPath}{raster_name}.tif"
        s3RasterObj = s3_client.get_object(Bucket="mappinjack-duc", Key=raster_path)
        gdal.FileFromMemBuffer(f"/vsimem/{raster_name}.tif", s3RasterObj["Body"].read())


def getGeoInfo(raster_name):
    FileName = f"/vsimem/{raster_name}.tif"
    SourceDS = gdal.Open(FileName, GA_ReadOnly)
    NDV = SourceDS.GetRasterBand(1).GetNoDataValue()
    xsize = SourceDS.RasterXSize
    ysize = SourceDS.RasterYSize
    GeoT = SourceDS.GetGeoTransform()
    Projection = osr.SpatialReference()
    Projection.ImportFromWkt(SourceDS.GetProjectionRef())
    DataType = SourceDS.GetRasterBand(1).DataType
    DataType = gdal.GetDataTypeName(DataType)
    return NDV, xsize, ysize, GeoT, Projection, DataType


def createGeoTiff(Name, Array, driver, NDV, xsize, ysize, GeoT, Projection, DataType):
    if DataType == "Float32":
        DataType = gdal.GDT_Float32
    newFileName = f"/vsimem/{Name}.tif"
    # Set nans to the original No Data Value
    Array[np.isnan(Array)] = NDV
    # Set up the dataset
    DataSet = driver.Create(newFileName, xsize, ysize, 1, gdal.GDT_Float32)  # DataType originally
    # the '1' is for band 1.
    DataSet.SetGeoTransform(GeoT)
    DataSet.SetProjection(Projection.ExportToWkt())
    print(Projection.ExportToWkt())
    # Write the array
    DataSet.GetRasterBand(1).WriteArray(Array)
    DataSet.GetRasterBand(1).SetNoDataValue(0)
    DataSet.FlushCache()
    return newFileName
