"""Export pipeline — orchestrates Markdown and RTF file generation.

Two public entry points:
- ``run_export_pipeline``         — solo submission (one ``ToolInstance``)
- ``run_session_export_pipeline`` — closed session (one ``ToolSession``)

Both functions catch all exceptions so that export failures never prevent
the archive record from being visible to the user.  A failure means the
download buttons will be absent from the archive detail view, but the
submission data itself is safely stored in the database.
"""
from .md_gen import generate_markdown, generate_session_markdown
from .rtf_gen import generate_rtf, generate_session_rtf
from archive.assets import cleanup_export_if_unreferenced


def run_export_pipeline(instance):
    """Generate per-instance MD and RTF exports for a solo submission.

    Export failures are non-fatal and silently logged.  The submission is
    already committed to the database before this runs, so a failure here
    only means the download files will be missing — the archive record itself
    is unaffected.
    """
    generated = []
    try:
        instance.md_file = generate_markdown(instance)
        generated.append(str(instance.md_file))
        instance.rtf_file = generate_rtf(instance)
        generated.append(str(instance.rtf_file))
        instance.save()
    except Exception as e:
        for value in generated:
            cleanup_export_if_unreferenced(value)
        print(f"Export Error for Instance {instance.id}: {str(e)}")


def run_session_export_pipeline(session):
    """Generate combined MD and RTF exports for a closed collaborative session.

    Like ``run_export_pipeline``, failures here are non-fatal.  The session
    is already marked as closed before this runs; a failure means no combined
    download file is produced, but the session close itself is not reversed.
    """
    generated = []
    try:
        session.md_file = generate_session_markdown(session)
        generated.append(str(session.md_file))
        session.rtf_file = generate_session_rtf(session)
        generated.append(str(session.rtf_file))
        session.save()
    except Exception as e:
        for value in generated:
            cleanup_export_if_unreferenced(value)
        print(f"Export Error for Session {session.id}: {str(e)}")
