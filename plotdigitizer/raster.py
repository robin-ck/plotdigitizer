"""Stage 5: extraction from raster images.

STUB. Not implemented in this version.

TODO (stage 5, see spec): native-resolution image from the PDF
(doc.extract_image), axis frame from dark rows/columns, tick sampling,
templates from legend markers (cv2.filter2D score for open markers,
morphological opening + connected components for filled markers),
per-point confidence (gut/mittel/gering), axis-break segments, and mandatory
WebPlotDigitizer correction. Test case: Blees et al. (2014), Fig. 1 b-d.
"""


def extract_panel(*args, **kwargs):
    raise NotImplementedError("raster extraction (stage 5) is not implemented yet")
