"""Materialize project files as ordinary named files, with rollback-safe updates."""

import errno
import hashlib
import os
import re
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import click
from flask import current_app, has_app_context
from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .extensions import db
from .models import FileNode, Project, StorageObject
from .storage import DC_PREFIX, dc_storage_root, is_dc_project, resolve_object_path


_registered = False


def history_root():
    return Path(os.path.expanduser(current_app.config.get("READABLE_HISTORY_ROOT") or str(Path(dc_storage_root()).parent / ".netdisk-storage-history")))


def safe_name(value, fallback="unnamed"):
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", str(value or "")).strip(" .") or fallback
    if name.split(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    if len(name.encode("utf-8")) > 220:
        stem, suffix = os.path.splitext(name)
        suffix = suffix[:24]
        name = stem.encode("utf-8")[:220 - len(suffix.encode("utf-8"))].decode("utf-8", "ignore") + suffix
    return name


def _unique_name(node, nodes):
    peers = sorted((n for n in nodes if n.parent_id == node.parent_id), key=lambda n: int(n.id))
    reserved = {safe_name(n.name).casefold() for n in peers}
    used = set()
    for peer in peers:
        name = safe_name(peer.name, f"file-{peer.id}")
        if name.casefold() in used:
            attempt = 1
            while True:
                marker = f" [{peer.id}]" if attempt == 1 else f" [{peer.id}-{attempt}]"
                stem, extension = os.path.splitext(name)
                suffix = marker + extension
                budget = 220 - len(suffix.encode("utf-8"))
                candidate = stem.encode("utf-8")[:budget].decode("utf-8", "ignore") + suffix
                if candidate.casefold() not in used and candidate.casefold() not in reserved:
                    name = candidate
                    break
                attempt += 1
        used.add(name.casefold())
        if int(peer.id) == int(node.id):
            return name
    raise ValueError("file node is absent from its project")


def node_relative_path(node, project, nodes):
    by_id = {int(n.id): n for n in nodes}
    parts = [_unique_name(node, nodes)]
    cursor, visited = node, {int(node.id)}
    while cursor.parent_id:
        parent = by_id.get(int(cursor.parent_id))
        if not parent or parent.deleted_at is not None or parent.scope != "project" or parent.project_id != project.id:
            raise ValueError("invalid file parent")
        if int(parent.id) in visited:
            raise ValueError("file parent cycle")
        visited.add(int(parent.id))
        if parent.parent_id is not None:
            parts.insert(0, _unique_name(parent, nodes))
        cursor = parent
    if node.type == "folder" and node.parent_id is None:
        parts = []
    marker = f" [{safe_name(project.key)[:32]} - {project.id}]"
    project_name = safe_name(project.name).encode("utf-8")[:220 - len(marker.encode("utf-8"))].decode("utf-8", "ignore")
    title = project_name + marker
    relative = f"{DC_PREFIX}projects/{int(project.id)}/tree/{title}" + ("/" + "/".join(parts) if parts else "")
    if len(relative) > 512:
        raise ValueError("readable file path is too long")
    return relative


def _digest(path):
    result = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            result.update(chunk)
    return result.hexdigest()


def _link_or_copy(source, target):
    try:
        os.link(source, target)
    except OSError as exc:
        if exc.errno not in (errno.EXDEV, errno.EPERM, errno.EACCES, errno.ENOTSUP):
            raise
        shutil.copyfile(source, target)


def _ensure_directory(path, session):
    missing = []
    cursor = Path(path)
    while not cursor.exists():
        missing.append(str(cursor))
        cursor = cursor.parent
    os.makedirs(path, exist_ok=True)
    session.info.setdefault("readable_created_dirs", []).extend(reversed(missing))


def _materialize(source, destination, changes, session):
    _ensure_directory(os.path.dirname(destination), session)
    old = None
    if os.path.exists(destination):
        pending = history_root() / ".pending"
        pending.mkdir(parents=True, exist_ok=True)
        old = str(pending / uuid.uuid4().hex)
        _link_or_copy(destination, old)
    # A 220-byte filename cannot accommodate a UUID appended to its basename.
    temporary = os.path.join(os.path.dirname(destination), ".netdisk-" + uuid.uuid4().hex + ".pending")
    try:
        _link_or_copy(source, temporary)
        os.replace(temporary, destination)
        changes.append((destination, old))
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def _lock_projects(session, project_ids):
    """Serialize physical changes before any related ORM update is flushed."""
    held = session.info.setdefault("readable_locked_projects", set())
    pending = sorted(set(map(int, project_ids)) - held)
    if pending:
        connection = session.connection()
        session.info["readable_connection_info"] = connection.info
        connection.info["readable_session"] = session
        connection.execute(select(Project.id).where(
            Project.id.in_(pending),
        ).order_by(Project.id).with_for_update()).all()
        held.update(pending)


def sync_project(project_id, session=None):
    session = session if session is not None else db.session()
    if not is_dc_project(project_id):
        return 0
    _lock_projects(session, [project_id])
    # Locking reads see the latest committed tree even when an earlier API
    # SELECT established a MySQL REPEATABLE READ snapshot before the lock wait.
    project = session.query(Project).filter_by(id=int(project_id)).populate_existing().with_for_update().one()
    nodes = session.query(FileNode).filter_by(scope="project", project_id=int(project_id), deleted_at=None).order_by(FileNode.id).populate_existing().with_for_update().all()
    directories = set()
    changes = session.info.setdefault("readable_changes", [])
    retire = session.info.setdefault("readable_retire", set())
    count = 0
    for node in sorted(nodes, key=lambda n: (n.type != "folder", int(n.id))):
        relative = node_relative_path(node, project, nodes)
        destination = resolve_object_path(relative)
        if node.type == "folder":
            _ensure_directory(destination, session)
            directories.add(destination)
            continue
        source_object = session.query(StorageObject).filter_by(id=int(node.storage_object_id)).populate_existing().with_for_update().first()
        if not source_object:
            raise ValueError("file content is missing")
        if source_object.storage_rel_path == relative:
            if not os.path.isfile(destination):
                raise FileNotFoundError("readable file content is missing")
            continue
        old_path = source_object.storage_rel_path
        source = resolve_object_path(old_path)
        if os.path.getsize(source) != int(source_object.size_bytes):
            raise ValueError("file size mismatch")
        digest = _digest(source)
        if source_object.sha256 and source_object.sha256 != digest:
            raise ValueError("file hash mismatch")
        _materialize(source, destination, changes, session)
        references = len(session.query(FileNode.id).filter(FileNode.storage_object_id == source_object.id, FileNode.deleted_at.is_(None)).with_for_update().all())
        stale = session.query(StorageObject).filter_by(storage_rel_path=relative).populate_existing().with_for_update().first()
        if stale and stale.id != source_object.id:
            if session.query(FileNode.id).filter(FileNode.storage_object_id == stale.id, FileNode.deleted_at.is_(None)).with_for_update().first():
                raise ValueError("readable file path collision")
            session.delete(stale)
            session.flush()
        if references > 1:
            copied = StorageObject(mime_type=source_object.mime_type, size_bytes=source_object.size_bytes,
                                   storage_rel_path=relative, sha256=digest, created_by=source_object.created_by)
            session.add(copied)
            session.flush()
            node.storage_object_id = int(copied.id)
        else:
            source_object.storage_rel_path = relative
            source_object.sha256 = digest
        session.flush()
        if old_path.startswith(DC_PREFIX):
            retire.add(old_path)
        count += 1
    session.info.setdefault("readable_current_dirs", {})[int(project_id)] = directories
    return count


def _snapshot_directories(session, project_id):
    snapshots = session.info.setdefault("readable_previous_dirs", {})
    if int(project_id) in snapshots:
        return
    snapshots[int(project_id)] = set()
    connection = session.connection()
    project_row = connection.execute(select(Project.__table__).where(Project.id == int(project_id)).with_for_update()).mappings().first()
    if not project_row:
        return
    project = SimpleNamespace(**dict(project_row))
    rows = connection.execute(select(FileNode.__table__).where(
        FileNode.scope == "project", FileNode.project_id == int(project_id), FileNode.deleted_at.is_(None),
    ).order_by(FileNode.id).with_for_update()).mappings().all()
    nodes = [SimpleNamespace(**dict(row)) for row in rows]
    for node in nodes:
        if node.type == "folder":
            snapshots[int(project_id)].add(resolve_object_path(node_relative_path(node, project, nodes)))


def _rollback_files(session):
    for path in sorted(session.info.pop("readable_removed_dirs", set()), key=lambda value: len(Path(value).parts)):
        os.makedirs(path, exist_ok=True)
    for destination, original in reversed(session.info.pop("readable_changes", [])):
        if original and os.path.exists(original):
            try:
                os.replace(original, destination)
            except OSError as exc:
                if exc.errno != errno.EXDEV:
                    raise
                temporary = os.path.join(os.path.dirname(destination), ".netdisk-" + uuid.uuid4().hex + ".pending")
                try:
                    shutil.copyfile(original, temporary)
                    os.replace(temporary, destination)
                    os.remove(original)
                finally:
                    if os.path.exists(temporary):
                        os.remove(temporary)
        elif os.path.isfile(destination):
            os.remove(destination)
    for path in reversed(session.info.pop("readable_created_dirs", [])):
        try:
            Path(path).rmdir()
        except OSError:
            pass
    for key in ("readable_retire", "readable_projects", "readable_retire_ready",
                "readable_previous_dirs", "readable_current_dirs", "readable_retired_dirs", "readable_staged_retire"):
        session.info.pop(key, None)


def _stage_retired_paths(session, relatives, directories):
    """Remove live paths while the project lock is held, with reversible backups."""
    retired = session.info.setdefault("readable_staged_retire", [])
    changes = session.info.setdefault("readable_changes", [])
    for relative in relatives:
        source = resolve_object_path(relative)
        if not os.path.isfile(source):
            continue
        pending = history_root() / ".pending"
        pending.mkdir(parents=True, exist_ok=True)
        original = str(pending / uuid.uuid4().hex)
        try:
            _link_or_copy(source, original)
        except Exception:
            if os.path.exists(original):
                os.remove(original)
            raise
        changes.append((source, original))
        os.remove(source)
        retired.append((original, relative))
    removed = session.info.setdefault("readable_removed_dirs", set())
    for path in sorted(directories, key=lambda value: len(Path(value).parts), reverse=True):
        try:
            Path(path).rmdir()
            removed.add(path)
        except OSError:
            # Only empty managed directories are removed. Preserve unknown files.
            pass


def _collect(session, _context, _instances):
    if not has_app_context() or not current_app.extensions.get("readable_storage") or not current_app.config.get("READABLE_STORAGE_ENABLED", True):
        return
    projects = session.info.setdefault("readable_projects", set())
    affected = set()
    for item in set(session.new) | set(session.dirty) | set(session.deleted):
        if isinstance(item, FileNode) and item.scope == "project" and item.project_id:
            projects.add(int(item.project_id))
            affected.add(int(item.project_id))
            if item.deleted_at is not None and item.storage_object_id:
                source = session.get(StorageObject, int(item.storage_object_id))
                if source and source.storage_rel_path.startswith(DC_PREFIX):
                    session.info.setdefault("readable_retire", set()).add(source.storage_rel_path)
        elif isinstance(item, Project) and item.id:
            projects.add(int(item.id))
            affected.add(int(item.id))
        elif isinstance(item, StorageObject):
            if item.id:
                references = {int(row[0]) for row in session.query(FileNode.project_id).filter(
                    FileNode.storage_object_id == item.id, FileNode.scope == "project", FileNode.project_id.isnot(None)
                )}
                projects.update(references)
                affected.update(references)
            if item in session.deleted and item.storage_rel_path.startswith(DC_PREFIX):
                session.info.setdefault("readable_retire", set()).add(item.storage_rel_path)
    dc_projects = {project_id for project_id in affected if is_dc_project(project_id)}
    _lock_projects(session, dc_projects)
    for project_id in sorted(dc_projects):
        _snapshot_directories(session, project_id)


def _before_commit(session):
    if not has_app_context() or not current_app.extensions.get("readable_storage") or not current_app.config.get("READABLE_STORAGE_ENABLED", True) or session.info.get("readable_syncing") or session.in_nested_transaction():
        return
    session.info["readable_syncing"] = True
    try:
        session.flush()
        for project_id in list(session.info.pop("readable_projects", set())):
            sync_project(project_id, session)
        session.flush()
        candidates = session.info.pop("readable_retire", set())
        retire_ready = [rel for rel in candidates if not session.query(FileNode.id).join(StorageObject, StorageObject.id == FileNode.storage_object_id).filter(FileNode.deleted_at.is_(None), StorageObject.storage_rel_path == rel).with_for_update().first()]
        current = session.info.get("readable_current_dirs", {})
        retired_dirs = set().union(*(
            previous - current.get(project_id, previous)
            for project_id, previous in session.info.get("readable_previous_dirs", {}).items()
        ))
        _stage_retired_paths(session, retire_ready, retired_dirs)
    except Exception:
        _rollback_files(session)
        raise
    finally:
        session.info.pop("readable_syncing", None)
        session.info.pop("readable_projects", None)


def _after_commit(session):
    if not has_app_context() or session.in_nested_transaction():
        return
    session.info.pop("readable_created_dirs", None)
    session.info.pop("readable_previous_dirs", None)
    session.info.pop("readable_current_dirs", None)
    session.info.pop("readable_removed_dirs", None)
    retired = session.info.pop("readable_staged_retire", [])
    retirement_backups = {pending for pending, _ in retired}
    for _, pending in session.info.pop("readable_changes", []):
        if pending and pending not in retirement_backups and os.path.exists(pending):
            try:
                os.remove(pending)
            except OSError:
                current_app.logger.warning("Readable storage backup cleanup postponed")
    for pending, relative in retired:
        source = Path(pending)
        if not source.is_file():
            continue
        target = history_root() / relative[len(DC_PREFIX):]
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                target = target.with_name(target.name + "." + uuid.uuid4().hex)
            shutil.move(str(source), str(target))
        except OSError:
            current_app.logger.warning("Readable storage history cleanup postponed")
            continue


def _transaction_ended(session, transaction):
    # Session.close() can roll back a failed database commit without after_rollback.
    if transaction.parent is None:
        if session.info.get("readable_changes") or session.info.get("readable_created_dirs") or session.info.get("readable_removed_dirs"):
            _rollback_files(session)
        session.info.pop("readable_locked_projects", None)
        connection_info = session.info.pop("readable_connection_info", None)
        if connection_info is not None and connection_info.get("readable_session") is session:
            connection_info.pop("readable_session", None)


def _before_database_rollback(connection):
    # Session.after_rollback runs after InnoDB releases its project locks.
    # Restore physical paths before DBAPI.rollback lets another writer proceed.
    session = connection.info.get("readable_session")
    if session is not None:
        _rollback_files(session)


def register_readable_storage(app):
    global _registered
    app.extensions["readable_storage"] = True
    if not _registered:
        event.listen(Session, "before_flush", _collect)
        event.listen(Session, "before_commit", _before_commit)
        event.listen(Session, "after_commit", _after_commit)
        event.listen(Session, "after_rollback", _rollback_files)
        event.listen(Session, "after_transaction_end", _transaction_ended)
        event.listen(Engine, "rollback", _before_database_rollback)
        _registered = True

    @app.cli.command("migrate-readable-storage")
    def migrate_command():
        """Pause writers, then materialize current filenames without compression."""
        total = 0
        for project in Project.query.order_by(Project.id).all():
            if is_dc_project(project.id):
                total += sync_project(project.id)
        db.session.commit()
        click.echo(f"readable_files={total}")
