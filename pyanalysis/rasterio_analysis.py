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
        "water": "minmaxinverse",
        "saturation": "minmax",
        "wetland": "minmaxinverse",
    }
    if raster_rescale_dict[nickname] is None:
        # Assuming only 1 and 0s allowed
        print(f"No rescaling for {nickname}")
        if nickname == "land":
            return numpy.where(a == 0, 0.01, a)
        else:
            return numpy.where(a > 1, 0, a)
    if raster_rescale_dict[nickname] == "minmaxinverse":
        print(f"Rescaling {nickname} using minmaxinverse")
        return (abs(a - numpy.nanmax(a))) / (numpy.nanmax(a) - numpy.nanmin(a))
    else:
        print(f"Rescaling {nickname} using minmax")
        return (a - numpy.nanmin(a)) / (numpy.nanmax(a) - numpy.nanmin(a))

def reclass_array(a):
    #jnb = JenksNaturalBreaks(nb_class=4)
    print("Reclassifying array")
    print("Raveling")
    #flat_array = a.ravel()
    print("Deleting 0s")
    #flat_array = numpy.delete(flat_array, [0])
    print("Creating breaks")
    #print(type(flat_array))
    #print(len(flat_array))
    #jnb.fit(flat_array)
    print('Fit complete')
    #breaks = jnb.inner_breaks_
    #flat_array = a.flatten()
    breaks = [0.2, 0.5, 0.7, 0.9, 1]#jenkspy.jenks_breaks(flat_array, nb_class=4)
    #breaks = [numpy.percentile(a, 30), numpy.percentile(a, 50), numpy.percentile(a, 70), numpy.percentile(a, 85), numpy.percentile(a, 100)]
    
    print("Reclassing")
    for i, b in enumerate(breaks):
        a = numpy.where((a <= b) & (a > 0), i+1, a)
        #numpy.where(a <= b and a > 0, i+1, a)
    return a


def lambda_handler(event, context):
    weights = event["body"]
    if not isinstance(weights, dict):
        weights = json.loads(weights)
    print(f"User input: {weights}")
    user_bounds = weights.pop("bounds")
    do_reclass = weights.pop("do_reclass")
    user_bounds = [user_bounds[0], user_bounds[3], user_bounds[2], user_bounds[1]]
    overlay_array = None
    profile = None
    bounds = None
    
    for nickname, raster_name in RASTERS.items():
        if weights[nickname] == 0:
            print(f"Weight is 0 for {nickname}. Skipping.")
            continue
        else:
            print(f"Weight is {weights[nickname]} for {nickname}. Processing.")

        print(f"Opening raster {raster_name}")
        with rasterio.open(f"s3://mappinjack-duc/full_rasters_unscaled/{raster_name}.tif") as src:
            bounds = from_bounds(*user_bounds, src.transform)
            band1 = src.read(1, window=bounds)  # Window(0, 0, 512, 256))
            if overlay_array is None:
                overlay_array = numpy.zeros(band1.shape, numpy.float32)
                profile = src.profile
                profile["height"], profile["width"] = band1.shape
                profile["nodata"] = numpy.nan
                profile["transform"] = rasterio.windows.transform(bounds, src.transform)
            weight = 1 * weights[nickname] / 100.0
            array = numpy.where(band1 is None or band1 == src.nodata, numpy.nan, band1)
            weighted_array = rescale_array(nickname, array) * weight
            overlay_array = numpy.add(overlay_array, weighted_array)
    
    # Reset nan to 0 for summing raster values
    overlay_array = numpy.nan_to_num(overlay_array)
    if do_reclass:
        overlay_array = reclass_array(overlay_array)
    profile["dtype"] = rasterio.float32
    s3_client = boto3.client("s3")
    with MemoryFile() as memfile:
        with memfile.open(**profile) as dataset:
            print("Writing raster to memory")
            dataset.write(overlay_array.astype(rasterio.float32), indexes=1)
            dataset.close()
        print("Writing raster to S3")
        file_key = "wetland_overlay.tif"
        s3_client.put_object(Body=memfile, Bucket="mappinjack-public", Key=file_key)
        s3 = boto3.resource("s3")
        object_acl = s3.ObjectAcl("mappinjack-public", file_key)
        object_acl.put(ACL="public-read")

    print("Success!")
    print(overlay_array)
    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "corsUrl": f"https://cors-anywhere.herokuapp.com/https://mappinjack-public.s3.ca-central-1.amazonaws.com/{file_key}",
                "downloadUrl": f"https://mappinjack-public.s3.ca-central-1.amazonaws.com/{file_key}",
            }
        ),
        "headers": {"Access-Control-Allow-Origin": "*", "Content-Type": "application/json"},
    }
