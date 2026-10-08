"""Independent, experimental SolidWorks part reader and native STEP conversion."""

ASSEMBLY_STEP_UNSUPPORTED = (
    'Assembly (.sldasm) STEP conversion is not supported by this reader. '
    'Complete assembly export needs the referenced component files, their saved '
    'configurations and instance placements. Convert the component .sldprt files '
    'individually, or supply an existing assembly STEP export.'
)
