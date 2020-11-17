import json
import boto3
import rasterio
from rasterio.io import MemoryFile
from rasterio.windows import from_bounds, Window
from rasterio.enums import Resampling
import numpy
import os

os.environ["GDAL_DATA"] = "/opt/share/gdal"
os.environ["PROJ_LIB"] = "/opt/share/proj"
RASTERS = {
    "hydric": "WetlandExtent",
    "land": "LandCover",
    "water": "OverlandFlow",
    "saturation": "SaturationIndex",
    "wetland": "WetlandDistance",
}


def rescale_array(nickname, a):
    raster_rescale_dict = {
        "hydric": None,
        "land": None,
        "water": "maxmin",
        "saturation": "minmax",
        "wetland": "maxmin",
    }
    return a / (a.max() / 255.0)
    if not raster_rescale_dict[nickname]:
        return a
    elif raster_rescale_dict[nickname] == "minmax":
        return (a - a.min()) / (a.max() - a.min())
    else:
        return (a - a.min()) / (a.max() - a.min())


def lambda_handler(event, context):
    weights = event["body"]
    if not isinstance(weights, dict):
        weights = json.loads(weights)
    print(f"Weights: {weights}")
    user_bounds = weights.pop("bounds")
    user_bounds = [user_bounds[0], user_bounds[3], user_bounds[2], user_bounds[1]]
    raster_arrays = {k: "" for k in RASTERS}
    overlay_array = None
    profile = None
    bounds = None
    nickname = "saturation"
    for nickname, raster_name in RASTERS.items():
        with rasterio.open(f"s3://mappinjack-duc/full_rasters_unscaled/{raster_name}.tif") as src:
            bounds = from_bounds(*user_bounds, src.transform)
            band1 = src.read(1, window=bounds)  # Window(0, 0, 512, 256))
            if overlay_array is None:
                overlay_array = numpy.zeros(band1.shape, numpy.float64)
                profile = src.profile
                profile["height"], profile["width"] = band1.shape
                profile["nodata"] = 1
                profile["transform"] = rasterio.windows.transform(bounds, src.transform)

            weight = 1 * weights[nickname] / 100.0
            weighted_array = rescale_array(nickname, band1) * weight
            weighted_array = numpy.where(
                weighted_array is None or weighted_array > 200, 0, weighted_array
            )
            overlay_array = numpy.add(overlay_array, weighted_array)
            # overlay_array = numpy.where(overlay_array is None or overlay_array > 10, 0, overlay_array)

    profile["dtype"] = rasterio.float32
    s3_client = boto3.client("s3")
    with MemoryFile() as memfile:
        with memfile.open(**profile) as dataset:
            dataset.write(overlay_array.astype(rasterio.float32), indexes=1)
            dataset.close()

        s3_client.put_object(Body=memfile, Bucket="mappinjack-public", Key="rasteriooutput.tif")
        s3 = boto3.resource("s3")
        object_acl = s3.ObjectAcl("mappinjack-public", "rasteriooutput.tif")
        object_acl.put(ACL="public-read")

    print(overlay_array)
    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "corsUrl": f"https://cors-anywhere.herokuapp.com/https://mappinjack-public.s3.ca-central-1.amazonaws.com/rasteriooutput.tif",
                "downloadUrl": f"https://mappinjack-public.s3.ca-central-1.amazonaws.com/rasteriooutput.io",
            }
        ),
        "headers": {"Access-Control-Allow-Origin": "*", "Content-Type": "application/json"},
    }
