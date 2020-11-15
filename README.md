# wetland-gis-analysis
Weighted overlay interface for wetland analysis

# Architecture

This library performs weighted overlay analysis in the cloud. Using pre-processed rasters that cover all of Southern Ontario, it provides a simple user interface to perform wetland restoration analysis in various study areas.

The web UI (`index.html`) builds an API query that is sent to to an API Gateway, which then triggers a Lambda function. The Lambda function then reads the pre-processed rasters from S3 and processes them using GDAL, and writes the output GeoTIFF back to S3 in a public bucket. Then, the weighted overlay results can be downloaded and used in any GIS program, or alternatively, visualized using [geotiff.io](http://app.geotiff.io/load).
