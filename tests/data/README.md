# Sample Datasets

These datasets are intentionally tiny and partly broken. They exist to exercise
Meerqat against realistic structural problems without requiring large imaging
assets.

Included scenarios:

- `valid_minimal`: one valid Phenix-style plate with matching metadata
- `missing_index`: missing `Index.xml`
- `xml_mismatch`: folder name does not match the XML plate identifier
- `missing_metadata`: plate exists but metadata is absent
- `mixed_modalities`: plate contains both TIFF and PNG files
