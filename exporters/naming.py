# Reserved for export filename helpers.
#
# Intended to hold the ``build_filename`` utility that constructs consistent
# archive filenames (``YYYYMMDD_<tool-slug>_<id>.<ext>``) for both solo
# submissions and session exports.  Currently the naming logic lives inline
# in ``md_gen.py`` and ``rtf_gen.py``; this module is a placeholder for
# a future extraction when a third export format is added.
