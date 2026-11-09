#!/usr/bin/env python3
"""Prepare a separate, pinned Huawei source checkout; never sync or access a phone."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

PLAN = Path(__file__).with_name("source-plan.json")
OVERLAY = "blanc-pinned.xml"
SHA = re.compile(r"[0-9a-f]{40}\Z")
SEGMENT = re.compile(r"[A-Za-z0-9_.-]+\Z")


class PreparationError(Exception):
    pass


def run(args, cwd=None):
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise PreparationError(
            f"Command failed: {shlex.join(args)}\n{result.stderr.strip()}"
        )
    return result.stdout.strip()


def valid_path(value):
    path = PurePosixPath(value)
    return (bool(path.parts) and not path.is_absolute() and str(path) == value
            and all(part not in (".", "..") and SEGMENT.fullmatch(part)
                    for part in path.parts))


def load_plan(path):
    plan = json.loads(path.read_text(encoding="utf-8"))
    if (plan["schema_version"] != 1 or plan["stage"] != "source-preparation"
            or plan["build_ready"] is not False or plan["boot_ready"] is not False):
        raise PreparationError("Unsupported plan or invalid preparation-only status.")
    manifest = plan["manifest"]
    if not SHA.fullmatch(manifest["revision"]):
        raise PreparationError("Manifest revision must be a full commit SHA.")
    if not re.fullmatch(r"https://github\.com/[\w.-]+/[\w.-]+\.git", manifest["repository"]):
        raise PreparationError("Expected a public HTTPS GitHub manifest URL.")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest["default_xml_sha256"]):
        raise PreparationError("Invalid default.xml SHA-256.")
    names, paths = set(), set()
    for project in plan["projects"]:
        name, location = project["name"], project["path"]
        if not valid_path(name) or len(PurePosixPath(name).parts) != 2:
            raise PreparationError(f"Invalid project name: {name}")
        if not valid_path(location) or not valid_path(project["branch"]):
            raise PreparationError(f"Invalid project path/branch: {name}")
        if name in names or location in paths:
            raise PreparationError(f"Duplicate project name/path: {name}")
        names.add(name)
        paths.add(location)
        if not SHA.fullmatch(project["revision"]) or not SHA.fullmatch(project["base_commit"]):
            raise PreparationError(f"Unresolved or invalid commit pin: {name}")
    if not plan["projects"]:
        raise PreparationError("The device overlay is empty.")
    return plan


def manifest_projects(directory, filename="default.xml", seen=None):
    seen = set() if seen is None else seen
    path = (directory / filename).resolve()
    if not path.is_relative_to(directory.resolve()) or path in seen:
        raise PreparationError(f"Unsafe or recursive manifest include: {filename}")
    seen.add(path)
    tree = ET.parse(path).getroot()
    projects = list(tree.findall("project"))
    for include in tree.findall("include"):
        projects.extend(manifest_projects(directory, include.attrib["name"], seen))
    return projects


def overlay_xml(plan, manifest_directory):
    existing = manifest_projects(manifest_directory)
    names = {p.attrib["name"] for p in existing}
    paths = {p.attrib.get("path", p.attrib["name"]) for p in existing}
    root = ET.Element("manifest")
    root.append(ET.Comment(" Generated from huawei/source-plan.json; edit JSON, then run huawei/bootstrap.py render. "))
    ET.SubElement(root, "remote", name="blanc-github", fetch="https://github.com")
    for project in plan["projects"]:
        if project["name"] in names or project["path"] in paths:
            raise PreparationError(f"Project conflicts with upstream manifest: {project['name']}")
        ET.SubElement(root, "project", name=project["name"], path=project["path"],
                      remote="blanc-github", revision=project["revision"],
                      upstream=f"refs/heads/{project['branch']}")
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=True) + "\n"


def preparation_overlay(plan, plan_path):
    directory = plan_path.resolve().parent.parent
    digest = hashlib.sha256((directory / "default.xml").read_bytes()).hexdigest()
    if digest != plan["manifest"]["default_xml_sha256"]:
        raise PreparationError("Preparation checkout default.xml differs from its upstream pin.")
    return overlay_xml(plan, directory)


def verify_manifest(source, plan):
    directory = source / ".repo" / "manifests"
    if not directory.is_dir():
        raise PreparationError("No initialized .repo/manifests checkout found.")
    head = run(["git", "rev-parse", "HEAD"], directory)
    if head != plan["manifest"]["revision"]:
        raise PreparationError(f"Manifest HEAD is {head}; expected the pinned upstream base.")
    if run(["git", "status", "--porcelain=v1", "--untracked-files=normal"], directory):
        raise PreparationError("Manifest checkout is dirty; it will not be changed.")
    selector = source / ".repo" / "manifest.xml"
    if selector.is_symlink():
        if selector.resolve() != (directory / "default.xml").resolve():
            raise PreparationError("Active repo manifest does not select default.xml.")
    else:
        root = ET.parse(selector).getroot()
        children = list(root)
        if (root.tag != "manifest" or root.attrib or (root.text or "").strip()
                or len(children) != 1 or children[0].tag != "include"
                or children[0].attrib != {"name": "default.xml"}
                or len(children[0]) or (children[0].text or "").strip()
                or (children[0].tail or "").strip()):
            raise PreparationError("Active repo manifest must select only default.xml.")
    digest = hashlib.sha256((directory / "default.xml").read_bytes()).hexdigest()
    if digest != plan["manifest"]["default_xml_sha256"]:
        raise PreparationError("default.xml differs from the pinned upstream file.")
    return directory


def install_overlay(source, plan):
    manifest = verify_manifest(source, plan)
    contents = overlay_xml(plan, manifest)
    directory = source / ".repo" / "local_manifests"
    destination = directory / OVERLAY
    if directory.exists() and any(p.name != OVERLAY for p in directory.glob("*.xml")):
        raise PreparationError("Other local manifests exist; review their interactions manually.")
    if destination.exists():
        if destination.read_text(encoding="utf-8") != contents:
            raise PreparationError("An existing device overlay differs; it will not be overwritten.")
        return "unchanged"
    directory.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         prefix=".blanc-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, destination)  # Atomic creation, without replacing another file.
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return "created"


def check_empty_destination(source, preparation_directory):
    if source.is_relative_to(preparation_directory.resolve()):
        raise PreparationError("Use a separate source directory outside the preparation checkout.")
    if source.exists() and (not source.is_dir() or any(source.iterdir())):
        raise PreparationError("init requires a new or empty directory; existing work is preserved.")


def initialize(source, plan, preparation_directory):
    check_empty_destination(source, preparation_directory)
    if any(not shutil.which(name) for name in ("repo", "git", "git-lfs")):
        raise PreparationError("Install repo, git and git-lfs before running init.")
    source.mkdir(parents=True, exist_ok=True)
    command = ["repo", "init", "-u", plan["manifest"]["repository"],
               "-b", plan["manifest"]["revision"], "--git-lfs", "--no-clone-bundle"]
    print(f"Running: {shlex.join(command)}", file=sys.stderr)
    result = subprocess.run(command, cwd=source)
    if result.returncode:
        raise PreparationError("repo init failed; inspect its partial checkout. No sync was run.")
    return install_overlay(source, plan)


def audit(source, plan):
    directory = verify_manifest(source, plan)
    expected = overlay_xml(plan, directory)
    overlay_directory = source / ".repo" / "local_manifests"
    if sorted(p.name for p in overlay_directory.glob("*.xml")) != [OVERLAY]:
        raise PreparationError("Expected exactly the pinned device local manifest.")
    if (overlay_directory / OVERLAY).read_text(encoding="utf-8") != expected:
        raise PreparationError("Device overlay differs from the source plan.")
    listed = run(["repo", "list", "-p"], source).splitlines()
    if not listed:
        raise PreparationError("repo did not list any source projects.")
    missing = [path for path in listed if not (source / path / ".git").exists()]
    if missing:
        raise PreparationError(f"Source sync is incomplete; missing {len(missing)} projects, including {missing[0]}.")
    for project in plan["projects"]:
        location = source / project["path"]
        if not (location / ".git").exists():
            raise PreparationError(f"Project has not been synced: {project['path']}")
        if run(["git", "rev-parse", "HEAD"], location) != project["revision"]:
            raise PreparationError(f"Project HEAD differs from its pin: {project['path']}")
    # -p labels any dirty project output. This command only reads Git state.
    changes = run(["repo", "forall", "-p", "-c",
                   "git status --porcelain=v1 --untracked-files=normal"], source)
    if changes:
        raise PreparationError(f"Source checkout has local changes; no sync/reset was attempted:\n{changes}")
    return "clean; device heads match; full platform revisions are not locked until repo manifest -r"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "render", "init", "overlay", "audit"))
    parser.add_argument("--source", type=Path, help="separate Android source checkout")
    parser.add_argument("--plan", type=Path, default=PLAN)
    args = parser.parse_args(argv)
    try:
        plan = load_plan(args.plan)
        generated = preparation_overlay(plan, args.plan)
        if args.command == "render":
            print(generated, end="")
            return 0
        if args.plan.with_name(OVERLAY).read_text(encoding="utf-8") != generated:
            raise PreparationError("Generated overlay is stale; regenerate it from the JSON with render.")
        status = "plan and generated overlay valid; no source download or build has been performed"
        if args.command != "check":
            if args.source is None:
                raise PreparationError("--source is required for this command.")
            source = args.source.expanduser().resolve()
            if args.command == "init":
                status = initialize(source, plan, args.plan.resolve().parent.parent)
            elif args.command == "overlay":
                status = install_overlay(source, plan)
            else:
                status = audit(source, plan)
        print(json.dumps({"command": args.command, "status": status,
                          "stage": plan["stage"], "build_ready": False, "boot_ready": False,
                          "manifest_revision": plan["manifest"]["revision"],
                          "device_project_count": len(plan["projects"]),
                          "tools": {name: shutil.which(name) for name in ("git", "git-lfs", "repo")}},
                         indent=2))
        return 0
    except (PreparationError, KeyError, TypeError, ValueError, OSError, ET.ParseError) as error:
        print(f"Source preparation stopped: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
