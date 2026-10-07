"""Storage lifecycle hooks for archived records and sessions."""
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from .assets import (
    attachment_references,
    canvas_references,
    cleanup_attachment_if_unreferenced,
    cleanup_canvas_if_unreferenced,
    cleanup_export_if_unreferenced,
)
from .models import ToolInstance, ToolSession


def _file_values(instance, fields):
    return {
        str(getattr(instance, field).name or '')
        for field in fields
        if getattr(instance, field)
    }


@receiver(pre_save, sender=ToolInstance)
def remember_replaced_instance_assets(sender, instance, **kwargs):
    if not instance.pk:
        instance._replaced_assets = (set(), [], set())
        return
    try:
        old = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        instance._replaced_assets = (set(), [], set())
        return
    update_fields = kwargs.get('update_fields')
    compare_payloads = update_fields is None or bool(
        {'payload_input', 'payload_output'} & set(update_fields)
    )
    compare_attachments = update_fields is None or 'attachments' in update_fields
    file_fields = {'html_file', 'md_file', 'rtf_file'}
    compared_file_fields = (
        file_fields if update_fields is None else file_fields & set(update_fields)
    )
    old_attachments = {
        key: item for item in (old.attachments or [])
        if isinstance(item, dict)
        for key in [(item.get('type'), item.get('public_id'))]
    }
    removed_keys = (
        set(old_attachments) - attachment_references(instance)
        if compare_attachments else set()
    )
    instance._replaced_assets = (
        (
            canvas_references(old) - canvas_references(instance)
            if compare_payloads else set()
        ),
        [old_attachments[key] for key in removed_keys],
        _file_values(old, compared_file_fields)
        - _file_values(instance, compared_file_fields),
    )


@receiver(post_save, sender=ToolInstance)
def cleanup_replaced_instance_assets(sender, instance, **kwargs):
    canvases, attachments, exports = getattr(
        instance, '_replaced_assets', (set(), [], set()),
    )
    session_id = instance.session_id
    for value in canvases:
        transaction.on_commit(lambda value=value: cleanup_canvas_if_unreferenced(value))
    for item in attachments:
        transaction.on_commit(
            lambda item=item, session_id=session_id:
            cleanup_attachment_if_unreferenced(item, session_id)
        )
    for value in exports:
        transaction.on_commit(lambda value=value: cleanup_export_if_unreferenced(value))


@receiver(post_delete, sender=ToolInstance)
def cleanup_deleted_instance_assets(sender, instance, **kwargs):
    instance._replaced_assets = (
        canvas_references(instance),
        [item for item in (instance.attachments or []) if isinstance(item, dict)],
        _file_values(instance, ('html_file', 'md_file', 'rtf_file')),
    )
    cleanup_replaced_instance_assets(sender, instance)


@receiver(pre_save, sender=ToolSession)
def remember_replaced_session_exports(sender, instance, **kwargs):
    if not instance.pk:
        instance._replaced_exports = set()
        return
    try:
        old = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        instance._replaced_exports = set()
        return
    file_fields = {'md_file', 'rtf_file'}
    update_fields = kwargs.get('update_fields')
    compared_fields = (
        file_fields if update_fields is None else file_fields & set(update_fields)
    )
    instance._replaced_exports = (
        _file_values(old, compared_fields)
        - _file_values(instance, compared_fields)
    )


@receiver(post_save, sender=ToolSession)
def cleanup_replaced_session_exports(sender, instance, **kwargs):
    for value in getattr(instance, '_replaced_exports', set()):
        transaction.on_commit(lambda value=value: cleanup_export_if_unreferenced(value))


@receiver(post_delete, sender=ToolSession)
def cleanup_deleted_session_exports(sender, instance, **kwargs):
    for value in _file_values(instance, ('md_file', 'rtf_file')):
        transaction.on_commit(lambda value=value: cleanup_export_if_unreferenced(value))