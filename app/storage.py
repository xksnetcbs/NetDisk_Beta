"""Resolve both storage roots without changing existing object addresses."""

import datetime as dt
import hashlib
import ntpath
import os
import shutil
import uuid

import click
from flask import current_app

from .extensions import db
from .models import FileNode, Project, ProjectMember, StorageObject, User


DC_PREFIX = "_special_storage/"


def dc_storage_root():
    return os.path.abspath(os.path.expanduser(current_app.config.get("SPECIAL_STORAGE_ROOT") or "~/Net_Disk"))


def legacy_storage_root():
    return os.path.abspath(os.path.expanduser(current_app.config["STORAGE_ROOT"]))


def _readable_incoming_root():
    history = current_app.config.get("READABLE_HISTORY_ROOT") or os.path.join(
        os.path.dirname(dc_storage_root()), ".netdisk-storage-history"
    )
    return os.path.join(os.path.abspath(os.path.expanduser(history)), ".incoming")


def is_dc_project(project_id):
    if not project_id:
        return False
    owner = User.query.filter_by(username=current_app.config.get("SPECIAL_STORAGE_USERNAME", "storage_admin"), role_system="super_admin").first()
    project = db.session.get(Project, int(project_id))
    if not owner or not project:
        return False
    return int(project.creator_id) == int(owner.id) or ProjectMember.query.filter_by(
        project_id=int(project.id), user_id=int(owner.id), role_project="creator"
    ).first() is not None


def project_namespace(project_id=None):
    return f"{DC_PREFIX}projects/{int(project_id)}/" if is_dc_project(project_id) else ""


def project_storage_root(project_id=None):
    return dc_storage_root() if is_dc_project(project_id) else legacy_storage_root()


def object_storage_root(rel_path):
    return dc_storage_root() if str(rel_path).replace("\\", "/").startswith(DC_PREFIX) else legacy_storage_root()


def resolve_object_path(rel_path, legacy_root=None):
    """Never allow stored paths or symlinks to escape their selected root."""
    value = str(rel_path or "").replace("\\", "/")
    special = value.startswith(DC_PREFIX)
    root = dc_storage_root() if special else (legacy_root or legacy_storage_root())
    relative = value[len(DC_PREFIX):] if special else value
    parts = relative.split("/")
    if (
        special and len(parts) >= 5 and parts[0] == "projects" and parts[1].isdigit()
        and parts[2:4] == ["incoming", "objects"]
    ):
        # Explicit addresses keep staging outside the named tree, even if readable
        # mode is later disabled. Existing objects retain their original roots.
        root = _readable_incoming_root()
        relative = "/".join(parts[:2] + parts[3:])
    elif special and len(parts) >= 4 and parts[0] == "projects" and parts[1].isdigit() and parts[2] == "tree":
        # Keep the stable project namespace in the DB, expose only human names on disk.
        relative = "/".join(parts[3:])
    if not relative or ntpath.splitdrive(relative)[0] or relative.startswith("/"):
        raise ValueError("invalid storage path")
    if any(part in ("", ".", "..") for part in relative.split("/")):
        raise ValueError("invalid storage path")
    root = os.path.realpath(os.path.expanduser(root))
    target = os.path.realpath(os.path.join(root, *relative.split("/")))
    if os.path.commonpath([root, target]) != root or target == root:
        raise ValueError("storage path escapes root")
    return target


def new_object_path(project_id=None):
    now = dt.datetime.now()
    namespace = project_namespace(project_id)
    if namespace and current_app.extensions.get("readable_storage") and current_app.config.get("READABLE_STORAGE_ENABLED", True):
        namespace += "incoming/"
    return f"{namespace}objects/{now.year:04d}/{now.month:02d}/{uuid.uuid4().hex}"


def path_matches_project(rel_path, project_id=None):
    namespace = project_namespace(project_id)
    value = str(rel_path).replace("\\", "/")
    return value.startswith(namespace) if namespace else not value.startswith(DC_PREFIX)


def _file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_object_to_project(source, project_id=None, legacy_root=None):
    """Copy before switching references; preserve originals for rollback."""
    rel_path = new_object_path(project_id)
    src = resolve_object_path(source.storage_rel_path, legacy_root=legacy_root)
    target = resolve_object_path(rel_path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    temporary = target + ".tmp"
    try:
        shutil.copyfile(src, temporary)
        digest = _file_hash(temporary)
        if os.path.getsize(temporary) != int(source.size_bytes) or digest != _file_hash(src):
            raise OSError("storage copy verification failed")
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    copied = StorageObject(
        mime_type=source.mime_type, size_bytes=source.size_bytes,
        storage_rel_path=rel_path, sha256=digest, created_by=source.created_by,
    )
    db.session.add(copied)
    try:
        db.session.flush()
    except Exception:
        os.remove(target)
        raise
    return copied


def object_for_project(source, project_id=None):
    if path_matches_project(source.storage_rel_path, project_id):
        return source
    return copy_object_to_project(source, project_id)


def migrate_dc_project(project_id, dry_run=False, source_root=None):
    """Split shared objects by project so other projects keep their addresses."""
    result = {"project_id": int(project_id), "copied": 0, "nodes": 0, "missing": [], "errors": []}
    if not is_dc_project(project_id):
        return result
    nodes = FileNode.query.filter_by(scope="project", project_id=int(project_id), type="file", deleted_at=None).all()
    grouped = {}
    for node in nodes:
        if node.storage_object_id:
            grouped.setdefault(int(node.storage_object_id), []).append(node)
    for object_id, references in grouped.items():
        source = db.session.get(StorageObject, object_id)
        if not source:
            result["missing"].append(object_id)
            continue
        try:
            src = resolve_object_path(source.storage_rel_path, legacy_root=source_root)
            if not os.path.isfile(src):
                result["missing"].append(object_id)
                continue
            if path_matches_project(source.storage_rel_path, project_id):
                continue
            if not dry_run:
                # Savepoint preserves other successful copies if one object fails.
                with db.session.begin_nested():
                    copied = copy_object_to_project(source, project_id, legacy_root=source_root)
                    for node in references:
                        node.storage_object_id = int(copied.id)
            result["copied"] += 1
            result["nodes"] += len(references)
        except (OSError, ValueError) as exc:
            result["errors"].append({"object_id": object_id, "type": type(exc).__name__})
    if not dry_run:
        db.session.commit()
    return result


def migrate_dc_storage(dry_run=False, source_root=None):
    return [migrate_dc_project(p.id, dry_run, source_root) for p in Project.query.order_by(Project.id).all() if is_dc_project(p.id)]


def register_storage_commands(app):
    @app.cli.command("migrate-dc-storage")
    @click.option("--dry-run", is_flag=True, help="Report available and missing objects without writing. Stop writers before migration.")
    @click.option("--source-root", type=click.Path(file_okay=False, exists=True), help="Explicit old storage directory, if configuration differs.")
    def migrate_command(dry_run, source_root):
        import json
        results = migrate_dc_storage(dry_run=dry_run, source_root=source_root)
        click.echo(json.dumps(results, ensure_ascii=False))
        if any(row["missing"] or row["errors"] for row in results):
            raise click.ClickException("Some source objects are unavailable; their references were preserved.")
