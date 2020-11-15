import json
import sys
import os
import base64

os.environ["GDAL_DATA"] = "/opt/share/gdal"
os.environ["PROJ_LIB"] = "/opt/share/proj"

import numpy as np

from osgeo import gdal, osr
from osgeo.gdalnumeric import *
from osgeo.gdalconst import *

import boto3
import io
s3_client = boto3.client('s3')
gdal.AllRegister()

#RASTERS = ["Clip_ExistingWetlands_Euc", "Clip_LandCoverSuitability", "Clip_OverlandFlow_Euclide", "Clip_SaturationIndex", "WetlandExtent1800"]
RASTERS = ["WetlandExtent", "LandCover", "OverlandFlow", "SaturationIndex", "WetlandDistance"]


def lambda_handler(event, context):
    for raster_name in RASTERS:
        raster_path = f"rasters3/{raster_name}.tif"
        s3_clientobj = s3_client.get_object(Bucket='mappinjack-duc', Key=raster_path)
        _r = gdal.FileFromMemBuffer(f'/vsimem/{raster_name}.tif', s3_clientobj["Body"].read())
    

    inDs = gdal.Open(f'/vsimem/{RASTERS[0]}.tif')
    band1 = inDs.GetRasterBand(1)
    rows = inDs.RasterYSize
    cols = inDs.RasterXSize
    
    driver = inDs.GetDriver()
    outDs = driver.Create(f'/vsimem/output.tif', cols, rows, 1, GDT_Float64)
    
    outBand = outDs.GetRasterBand(1)
    outData = numpy.zeros((rows,cols), numpy.float64)

    for raster_name in RASTERS:
        weight = 1 #TODO
        raster = gdal.Open(f'/vsimem/{raster_name}.tif')
        rasterArray = raster.GetRasterBand(1).ReadAsArray(0,0,cols,rows)
        rasterArray = np.where(rasterArray is None or rasterArray > 10, 0, rasterArray) 
        weightedArray = rasterArray * weight
        # TODO add masks
        outData = np.add(outData, weightedArray)

    print(outData)
    
    colors = gdal.ColorTable()
    colors.CreateColorRamp(0, (229, 245, 249), 1, (153, 216, 201))
    colors.CreateColorRamp(2, (153, 216, 201), 3, (44, 162, 95))
    outDs.GetRasterBand(1).SetRasterColorTable(colors)
    outDs.GetRasterBand(1).SetRasterColorInterpretation(gdal.GCI_PaletteIndex)
    
    
    NDV, xsize, ysize, GeoT, Projection, DataType = GetGeoInfo("WetlandExtent")
    
    # Set up the GTiff driver
    driver = gdal.GetDriverByName('GTiff')
    print(Projection)
    # Now turn the array into a GTiff.
    NewFileName = CreateGeoTiff('output', outData, driver, NDV, 
                                xsize, ysize, GeoT, Projection, DataType)

    f = gdal.VSIFOpenL('/vsimem/output.tif', 'rb')
    gdal.VSIFSeekL(f, 0, 2)  # seek to end
    size = gdal.VSIFTellL(f)
    gdal.VSIFSeekL(f, 0, 0)  # seek to beginning
    data = gdal.VSIFReadL(1, size, f)
    gdal.VSIFCloseL(f)


    print(s3_client.put_object(Body=data, Bucket='mappinjack-public', Key='new.tif'))
    s3 = boto3.resource('s3')
    object_acl = s3.ObjectAcl('mappinjack-public', 'new.tif')
    response = object_acl.put(ACL='public-read')
    return {'statusCode': 200, 
            "body": json.dumps({"url": "https://cors-anywhere.herokuapp.com/https://mappinjack-public.s3.ca-central-1.amazonaws.com/new.tif"}),   
            "headers": { "Access-Control-Allow-Origin": "*", 'Content-Type': 'application/json'}
        }
    # Follow: https://gis.stackexchange.com/questions/57005/python-gdal-write-new-raster-using-projection-from-old
    
def GetGeoInfo(raster_name):
    FileName = f'/vsimem/{raster_name}.tif'
    #FileMem = gdal.FileFromMemBuffer(FileName, s3_clientobj["Body"].read())
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
    
def CreateGeoTiff(Name, Array, driver, NDV, 
                  xsize, ysize, GeoT, Projection, DataType):
    if DataType == 'Float32':
        DataType = gdal.GDT_Float32
    NewFileName = f'/vsimem/{Name}.tif'
    # Set nans to the original No Data Value
    Array[np.isnan(Array)] = NDV
    # Set up the dataset
    DataSet = driver.Create( NewFileName, xsize, ysize, 1, gdal.GDT_Float32 ) #DataType originally
            # the '1' is for band 1.
    DataSet.SetGeoTransform(GeoT)
    DataSet.SetProjection( Projection.ExportToWkt() )
    print(Projection.ExportToWkt())
    # Write the array
    DataSet.GetRasterBand(1).WriteArray( Array )
    DataSet.GetRasterBand(1).SetNoDataValue(0)
    DataSet.FlushCache()
    return NewFileName