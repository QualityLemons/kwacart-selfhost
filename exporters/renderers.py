# Reserved for shared content-rendering helpers.
#
# Intended to hold functions that transform a ``ToolInstance.payload_output``
# dict into formatted strings (section headings, field values) reusable by
# both the Markdown and RTF generators.  Currently each generator renders
# content inline; this module is a placeholder for a future refactor to
# eliminate the duplication between ``md_gen.py`` and ``rtf_gen.py``.
