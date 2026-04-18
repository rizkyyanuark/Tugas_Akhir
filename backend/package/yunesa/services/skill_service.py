from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession
from yunesa import config as sys_config
from yunesa.repositories.skill_repository import SkillRepository
from yunesa.services.mcp_service import get_enabled_mcp_server_names
from yunesa.storage.postgres.models_business import Skill
from yunesa.utils.logging_config import logger

SKILL_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SKILL_NAME_PATTERN = SKILL_SLUG_PATTERN

TEXT_FILE_EXTENSIONS = {
    ".md",
    ".txt",
    ".py",
    ".js",
    ".ts",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".xml",
    ".html",
    ".css",
    ".sql",
    ".sh",
    ".bat",
    ".ps1",
    ".env",
    ".csv",
    ".tsv",
    ".rst",
    ".ipynb",
    ".vue",
    ".jsx",
    ".tsx",
}

BUILTIN_SKILL_OPERATOR = "builtin-system"
_THREAD_SKILLS_LOCK = threading.Lock()
_THREAD_SKILLS_LOCKS: dict[str, threading.Lock] = {}


class BuiltinSkillUpdateConflictError(ValueError):
    def __init__(self, message: str):
        super().__init__(message)
        self.needs_confirm = True


def _get_thread_skills_lock(thread_id: str) -> threading.Lock:
    with _THREAD_SKILLS_LOCK:
        lock = _THREAD_SKILLS_LOCKS.get(thread_id)
        if lock is None:
            lock = threading.Lock()
            _THREAD_SKILLS_LOCKS[thread_id] = lock
        return lock


def _normalize_string_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        item = value.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


def is_valid_skill_slug(slug: str) -> bool:
    if not isinstance(slug, str):
        return False
    return bool(SKILL_SLUG_PATTERN.match(slug.strip()))


def get_skills_root_dir() -> Path:
    root = Path(sys_config.save_dir) / "skills"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_thread_skills_root_dir(thread_id: str) -> Path:
    safe_thread_id = str(thread_id or "").strip()
    if not safe_thread_id:
        raise ValueError("thread_id is required")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", safe_thread_id):
        raise ValueError("thread_id contains invalid characters")

    root = Path(sys_config.save_dir) / "threads" / safe_thread_id / "skills"
    root.mkdir(parents=True, exist_ok=True)
    return root


def sync_thread_visible_skills(thread_id: str, selected_slugs: list[str] | None) -> Path:
    skills_root = get_skills_root_dir().resolve()
    thread_skills_root = get_thread_skills_root_dir(thread_id)
    normalized_slugs = [slug for slug in _normalize_string_list(
        selected_slugs) if is_valid_skill_slug(slug)]
    visible_slugs = set(normalized_slugs)
    with _get_thread_skills_lock(thread_id):
        for entry in thread_skills_root.iterdir():
            if entry.name in visible_slugs:
                continue
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()

        for slug in normalized_slugs:
            source_dir = (skills_root / slug).resolve()
            target_dir = thread_skills_root / slug

            try:
                source_dir.relative_to(skills_root)
            except ValueError:
                continue
            if not source_dir.is_dir():
                if target_dir.exists() or target_dir.is_symlink():
                    if target_dir.is_dir() and not target_dir.is_symlink():
                        shutil.rmtree(target_dir)
                    else:
                        target_dir.unlink()
                continue

            if target_dir.exists():
                if target_dir.is_symlink():
                    target_dir.unlink()
                elif target_dir.is_dir():
                    if _dirs_equal(target_dir, source_dir):
                        continue
                    shutil.rmtree(target_dir)
                else:
                    target_dir.unlink()

            temp_target = thread_skills_root / \
                f".{slug}.tmp-{uuid.uuid4().hex[:8]}"
            try:
                shutil.copytree(source_dir, temp_target, symlinks=False)
                temp_target.rename(target_dir)
            finally:
                if temp_target.exists():
                    shutil.rmtree(temp_target, ignore_errors=True)

    return thread_skills_root


def get_builtin_skill_specs() -> list[Any]:
    from yunesa.agents.skills.buildin import BUILTIN_SKILLS

    return BUILTIN_SKILLS


def _get_builtin_skill_spec_or_raise(slug: str) -> Any:
    normalized_slug = slug.strip() if isinstance(slug, str) else ""
    for spec in get_builtin_skill_specs():
        if getattr(spec, "slug", "").strip() == normalized_slug:
            return spec
    raise ValueError(f"Built-in skill '{slug}' does not exist")


def _build_builtin_skill_dir_path(slug: str) -> str:
    return (Path("skills") / slug).as_posix()


def _is_builtin_managed(item: Skill, slug: str) -> bool:
    expected_dir = _build_builtin_skill_dir_path(slug)
    if item.dir_path != expected_dir:
        return False
    return (item.created_by or "") in {"system", BUILTIN_SKILL_OPERATOR}


def _dirs_equal(dir1: Path, dir2: Path) -> bool:
    """Check whether two directories have identical file contents by file list."""
    if not dir1.exists() or not dir2.exists():
        return False
    list1 = sorted([f.relative_to(dir1)
                   for f in dir1.rglob("*") if f.is_file()])
    list2 = sorted([f.relative_to(dir2)
                   for f in dir2.rglob("*") if f.is_file()])
    return list1 == list2


def _compute_dir_hash(source_dir: Path) -> str:
    hasher = hashlib.sha256()
    file_paths = sorted(
        path for path in source_dir.rglob("*") if path.is_file())
    for file_path in file_paths:
        relative_path = file_path.relative_to(source_dir).as_posix()
        hasher.update(relative_path.encode("utf-8"))
        hasher.update(b"\0")
        with file_path.open("rb") as f:
            while chunk := f.read(1024 * 1024):
                hasher.update(chunk)
        hasher.update(b"\0")
    return hasher.hexdigest()


def _copy_skill_target(target_dir: Path, source_dir: Path) -> None:
    if target_dir.is_symlink():
        target_dir.unlink()
    elif target_dir.exists():
        if _dirs_equal(target_dir, source_dir):
            return
        raise ValueError(
            f"skill directory already exists and is not a managed built-in target: {target_dir}")

    shutil.copytree(source_dir, target_dir, symlinks=False, dirs_exist_ok=True)


def _replace_skill_target(target_dir: Path, source_dir: Path) -> None:
    temp_target = target_dir.with_name(
        f".{target_dir.name}.tmp-{uuid.uuid4().hex[:8]}")
    trash_dir: Path | None = None
    if temp_target.exists():
        shutil.rmtree(temp_target, ignore_errors=True)

    shutil.copytree(source_dir, temp_target, symlinks=False)
    try:
        if target_dir.exists():
            trash_dir = target_dir.with_name(
                f".{target_dir.name}.bak-{uuid.uuid4().hex[:8]}")
            target_dir.rename(trash_dir)
        temp_target.rename(target_dir)
    except Exception:
        shutil.rmtree(temp_target, ignore_errors=True)
        if trash_dir and trash_dir.exists() and not target_dir.exists():
            trash_dir.rename(target_dir)
        raise

    if trash_dir and trash_dir.exists():
        shutil.rmtree(trash_dir, ignore_errors=True)


async def get_skill_dependency_options(db: AsyncSession) -> dict[str, list[str] | list[dict]]:
    # Execute three independent operations concurrently.
    from yunesa.services.tool_service import get_tool_metadata

    async def get_skills():
        repo = SkillRepository(db)
        return await repo.list_all()

    def get_tools():
        all_tools = get_tool_metadata()
        return [{"id": tool["id"], "name": tool.get("name", tool["id"])} for tool in all_tools]

    items, tool_list, mcp_names = await asyncio.gather(
        get_skills(),
        asyncio.to_thread(get_tools),
        get_enabled_mcp_server_names(db=db),
    )

    return {
        "tools": tool_list,
        "mcps": mcp_names,
        "skills": [item.slug for item in items],
    }


async def list_skills(db: AsyncSession) -> list[Skill]:
    repo = SkillRepository(db)
    return await repo.list_all()


def _get_all_tool_names() -> list[str]:
    """Get all tool names (including built-in and other sources)."""
    from yunesa.services.tool_service import get_tool_metadata

    all_tools = get_tool_metadata()
    return [tool["id"] for tool in all_tools]


async def _validate_dependencies(
    *,
    slug: str,
    tool_dependencies: list[str],
    mcp_dependencies: list[str],
    skill_dependencies: list[str],
    available_skill_slugs: set[str],
) -> tuple[list[str], list[str], list[str]]:
    tools = _normalize_string_list(tool_dependencies)
    mcps = _normalize_string_list(mcp_dependencies)
    skills = _normalize_string_list(skill_dependencies)

    # Verify all tools (not only built-ins).
    available_tools = set(_get_all_tool_names())
    invalid_tools = [name for name in tools if name not in available_tools]
    if invalid_tools:
        raise ValueError(
            f"Invalid tool dependencies found: {', '.join(invalid_tools)}")

    available_mcps = set(await get_enabled_mcp_server_names(db=None))
    invalid_mcps = [name for name in mcps if name not in available_mcps]
    if invalid_mcps:
        raise ValueError(
            f"Invalid MCP dependencies found: {', '.join(invalid_mcps)}")

    invalid_skills = [
        name for name in skills if name not in available_skill_slugs]
    if invalid_skills:
        raise ValueError(
            f"Invalid skill dependencies found: {', '.join(invalid_skills)}")

    if slug in skills:
        raise ValueError("skill_dependencies cannot include itself")

    return tools, mcps, skills


async def update_skill_dependencies(
    db: AsyncSession,
    *,
    slug: str,
    tool_dependencies: list[str],
    mcp_dependencies: list[str],
    skill_dependencies: list[str],
    updated_by: str | None,
) -> Skill:
    item = await get_skill_or_raise(db, slug)
    repo = SkillRepository(db)
    skill_items = await repo.list_all()
    available_skill_slugs = {skill.slug for skill in skill_items}
    tools, mcps, skills = await _validate_dependencies(
        slug=slug,
        tool_dependencies=tool_dependencies,
        mcp_dependencies=mcp_dependencies,
        skill_dependencies=skill_dependencies,
        available_skill_slugs=available_skill_slugs,
    )

    return await repo.update_dependencies(
        item,
        tool_dependencies=tools,
        mcp_dependencies=mcps,
        skill_dependencies=skills,
        updated_by=updated_by,
    )


def _validate_skill_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("SKILL.md frontmatter is missing name")
    if len(name) > 128:
        raise ValueError("skill name length cannot exceed 128")
    if not SKILL_NAME_PATTERN.match(name):
        raise ValueError(
            "skill name must use lowercase letters/numbers/hyphens and cannot contain consecutive hyphens")
    return name


def _split_frontmatter(content: str) -> tuple[str, str]:
    if not content.startswith("---"):
        raise ValueError("SKILL.md is missing valid frontmatter (--- ... ---)")

    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md is missing valid frontmatter (--- ... ---)")

    frontmatter_lines: list[str] = []
    body_start = 0
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body_start = index + 1
            break
        frontmatter_lines.append(line)
    else:
        raise ValueError("SKILL.md is missing valid frontmatter (--- ... ---)")

    frontmatter_raw = "".join(frontmatter_lines)
    body = "".join(lines[body_start:])
    return frontmatter_raw, body


def _parse_skill_markdown(content: str) -> tuple[str, str, dict[str, Any]]:
    frontmatter_raw, _body = _split_frontmatter(content)
    try:
        data = yaml.safe_load(frontmatter_raw)
    except yaml.YAMLError as e:
        raise ValueError(f"SKILL.md frontmatter YAML parsefailed: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("SKILL.md frontmatter must be an object")

    name = _validate_skill_name(str(data.get("name", "")))
    description = str(data.get("description", "")).strip()
    if not description:
        raise ValueError("SKILL.md frontmatter is missing description")

    return name, description, data


def _rewrite_frontmatter_name(content: str, new_name: str) -> str:
    frontmatter_raw, body = _split_frontmatter(content)
    data = yaml.safe_load(frontmatter_raw)
    if not isinstance(data, dict):
        raise ValueError("SKILL.md frontmatter must be an object")
    data["name"] = new_name
    dumped = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{dumped}\n---\n{body}"


def _validate_zip_paths(zip_file: zipfile.ZipFile) -> None:
    for name in zip_file.namelist():
        pure = PurePosixPath(name)
        if pure.is_absolute():
            raise ValueError(f"ZIP contains unsafe absolute path: {name}")
        if ".." in pure.parts:
            raise ValueError(f"ZIP contains path traversal segment: {name}")


async def _generate_available_slug(repo: SkillRepository, base_slug: str) -> str:
    root = get_skills_root_dir()
    if not await repo.exists_slug(base_slug) and not (root / base_slug).exists():
        return base_slug

    idx = 2
    while True:
        candidate = f"{base_slug}-v{idx}"
        if not await repo.exists_slug(candidate) and not (root / candidate).exists():
            return candidate
        idx += 1


async def _import_skill_dir_impl(
    db: AsyncSession,
    *,
    source_skill_dir: Path,
    created_by: str | None,
) -> Skill:
    repo = SkillRepository(db)
    skills_root = get_skills_root_dir()

    skill_md_path = source_skill_dir / "SKILL.md"
    if not skill_md_path.exists() or not skill_md_path.is_file():
        raise ValueError("skill directory is missing root-level SKILL.md")

    content = skill_md_path.read_text(encoding="utf-8")
    parsed_name, parsed_desc, _ = _parse_skill_markdown(content)

    final_slug = await _generate_available_slug(repo, parsed_name)
    final_name = parsed_name
    with tempfile.TemporaryDirectory(prefix=".skill-import-", dir=str(skills_root.parent)) as temp_root:
        temp_root_path = Path(temp_root)
        stage_dir = temp_root_path / "stage"
        shutil.copytree(source_skill_dir, stage_dir)

        if final_slug != parsed_name:
            final_name = final_slug
            content = _rewrite_frontmatter_name(content, final_name)
            (stage_dir / "SKILL.md").write_text(content, encoding="utf-8")

        temp_target = skills_root / f".{final_slug}.tmp-{uuid.uuid4().hex[:8]}"
        if temp_target.exists():
            shutil.rmtree(temp_target)
        shutil.move(str(stage_dir), str(temp_target))

        final_dir = skills_root / final_slug
        if final_dir.exists():
            shutil.rmtree(temp_target, ignore_errors=True)
            raise ValueError(
                f"skill directory conflict, please retry: {final_slug}")
        temp_target.rename(final_dir)

        try:
            item = await repo.create(
                slug=final_slug,
                name=final_name,
                description=parsed_desc,
                tool_dependencies=[],
                mcp_dependencies=[],
                skill_dependencies=[],
                dir_path=(Path("skills") / final_slug).as_posix(),
                created_by=created_by,
            )
        except Exception:
            shutil.rmtree(final_dir, ignore_errors=True)
            raise

    return item


def _resolve_skill_dir(item: Skill) -> Path:
    dir_path = Path(item.dir_path)
    if dir_path.is_absolute():
        return dir_path
    return (Path(sys_config.save_dir) / dir_path).resolve()


def _resolve_relative_path(skill_dir: Path, relative_path: str, *, allow_root: bool = False) -> tuple[Path, str]:
    rel = (relative_path or "").strip().replace("\\", "/")
    rel = rel.lstrip("/")
    if not rel and not allow_root:
        raise ValueError("path cannot be empty")
    pure = PurePosixPath(rel) if rel else PurePosixPath(".")
    if ".." in pure.parts:
        raise ValueError(
            "Invalid path: parent path references are not allowed")

    target = (skill_dir / pure).resolve()
    try:
        target.relative_to(skill_dir)
    except ValueError:
        raise ValueError("Invalid path: out-of-bounds access denied") from None

    return target, rel


def _is_text_path(path: Path) -> bool:
    if path.name == "SKILL.md":
        return True
    suffix = path.suffix.lower()
    return suffix in TEXT_FILE_EXTENSIONS


def _build_tree(path: Path, base_dir: Path) -> list[dict[str, Any]]:
    children: list[dict[str, Any]] = []
    for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        rel = child.relative_to(base_dir).as_posix()
        if child.is_dir():
            children.append(
                {
                    "name": child.name,
                    "path": rel,
                    "is_dir": True,
                    "children": _build_tree(child, base_dir),
                }
            )
        else:
            children.append(
                {
                    "name": child.name,
                    "path": rel,
                    "is_dir": False,
                }
            )
    return children


async def import_skill_zip(
    db: AsyncSession,
    *,
    filename: str,
    file_bytes: bytes,
    created_by: str | None,
) -> Skill:
    normalized_filename = filename.lower()
    is_zip_upload = normalized_filename.endswith(".zip")
    is_skill_md_upload = normalized_filename.endswith("skill.md")
    if not is_zip_upload and not is_skill_md_upload:
        raise ValueError("Only .zip or SKILL.md uploads are supported")

    skills_root = get_skills_root_dir()

    with tempfile.TemporaryDirectory(prefix=".skill-import-", dir=str(skills_root.parent)) as temp_root:
        temp_root_path = Path(temp_root)
        extract_dir = temp_root_path / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)
        if is_zip_upload:
            zip_path = temp_root_path / "upload.zip"
            zip_path.write_bytes(file_bytes)

            with zipfile.ZipFile(zip_path, "r") as zf:
                _validate_zip_paths(zf)
                zf.extractall(extract_dir)

            skill_md_files = list(extract_dir.rglob("SKILL.md"))
            if len(skill_md_files) != 1:
                raise ValueError(
                    "ZIP must contain exactly one skill (detected one SKILL.md)")

            skill_md_path = skill_md_files[0]
            source_skill_dir = skill_md_path.parent
        else:
            source_skill_dir = extract_dir
            skill_md_path = source_skill_dir / "SKILL.md"
            skill_md_path.write_bytes(file_bytes)

        return await _import_skill_dir_impl(
            db,
            source_skill_dir=source_skill_dir,
            created_by=created_by,
        )


async def import_skill_dir(
    db: AsyncSession,
    *,
    source_dir: Path | str,
    created_by: str | None,
) -> Skill:
    source_skill_dir = Path(source_dir).resolve()
    # Confine to the system temp directory to prevent path traversal
    tmp_root = Path(tempfile.gettempdir()).resolve()
    if not source_skill_dir.is_relative_to(tmp_root):
        raise ValueError("skilldirectorypathinvalid")
    if not source_skill_dir.exists() or not source_skill_dir.is_dir():
        raise ValueError("skilldirectorydoes not exist")
    return await _import_skill_dir_impl(
        db,
        source_skill_dir=source_skill_dir,
        created_by=created_by,
    )


async def get_skill_or_raise(db: AsyncSession, slug: str) -> Skill:
    slug = slug.strip() if isinstance(slug, str) else ""
    if not is_valid_skill_slug(slug):
        raise ValueError("invalid skill slug")

    repo = SkillRepository(db)
    item = await repo.get_by_slug(slug)
    if not item:
        raise ValueError(f"skill '{slug}' does not exist")
    return item


async def get_skill_tree(db: AsyncSession, slug: str) -> list[dict[str, Any]]:
    item = await get_skill_or_raise(db, slug)
    skill_dir = _resolve_skill_dir(item)
    if not skill_dir.exists() or not skill_dir.is_dir():
        raise ValueError(f"skilldirectorydoes not exist: {item.dir_path}")
    return _build_tree(skill_dir, skill_dir)


async def read_skill_file(db: AsyncSession, slug: str, relative_path: str) -> dict[str, Any]:
    item = await get_skill_or_raise(db, slug)
    skill_dir = _resolve_skill_dir(item)
    target, rel = _resolve_relative_path(skill_dir, relative_path)
    if not target.exists() or not target.is_file():
        raise ValueError(f"filedoes not exist: {relative_path}")
    if not _is_text_path(target):
        raise ValueError("Only text file reading is supported")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"Unsupported file encoding (UTF-8 only): {e}") from e

    return {"path": rel, "content": content}


async def create_skill_node(
    db: AsyncSession,
    *,
    slug: str,
    relative_path: str,
    is_dir: bool,
    content: str | None,
    updated_by: str | None,
) -> None:
    item = await get_skill_or_raise(db, slug)
    if item.is_builtin:
        raise ValueError("Built-in skills cannot be modified directly")
    skill_dir = _resolve_skill_dir(item)
    target, _ = _resolve_relative_path(skill_dir, relative_path)
    if target.exists():
        raise ValueError("Target already exists")

    if is_dir:
        target.mkdir(parents=True, exist_ok=False)
        return

    if not _is_text_path(target):
        raise ValueError("Only text file creation is supported")

    target.parent.mkdir(parents=True, exist_ok=True)

    # Write file first, then update metadata.
    target.write_text(content or "", encoding="utf-8")

    await _update_skill_metadata_if_skills_md(db, item, content or "", skill_dir, target, updated_by)


async def update_skill_file(
    db: AsyncSession,
    *,
    slug: str,
    relative_path: str,
    content: str,
    updated_by: str | None,
) -> None:
    item = await get_skill_or_raise(db, slug)
    if item.is_builtin:
        raise ValueError("Built-in skills cannot be modified directly")
    skill_dir = _resolve_skill_dir(item)
    target, _ = _resolve_relative_path(skill_dir, relative_path)
    if not target.exists() or not target.is_file():
        raise ValueError("filedoes not exist")
    if not _is_text_path(target):
        raise ValueError("Only text file editing is supported")

    await _update_skill_metadata_if_skills_md(db, item, content, skill_dir, target, updated_by)

    target.write_text(content, encoding="utf-8")


async def _update_skill_metadata_if_skills_md(
    db: AsyncSession,
    item: Skill,
    content: str,
    skill_dir: Path,
    target: Path,
    updated_by: str | None,
) -> None:
    """If the target file is SKILL.md, parse and update metadata."""
    if target.name == "SKILL.md" and target.parent == skill_dir:
        parsed_name, parsed_desc, _ = _parse_skill_markdown(content)
        if parsed_name != item.slug:
            raise ValueError(
                "SKILL.md frontmatter.name must match the skill slug")
        repo = SkillRepository(db)
        await repo.update_metadata(item, name=parsed_name, description=parsed_desc, updated_by=updated_by)


async def delete_skill_node(db: AsyncSession, *, slug: str, relative_path: str) -> None:
    item = await get_skill_or_raise(db, slug)
    if item.is_builtin:
        raise ValueError("Built-in skills cannot be modified directly")
    skill_dir = _resolve_skill_dir(item)
    target, rel = _resolve_relative_path(
        skill_dir, relative_path, allow_root=False)
    if not target.exists():
        raise ValueError("Target does not exist")

    if rel == "SKILL.md":
        raise ValueError("Deleting root SKILL.md is not allowed")

    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()


async def export_skill_zip(db: AsyncSession, slug: str) -> tuple[str, str]:
    item = await get_skill_or_raise(db, slug)
    skill_dir = _resolve_skill_dir(item)
    if not skill_dir.exists() or not skill_dir.is_dir():
        raise ValueError("skilldirectorydoes not exist")

    fd, export_path = tempfile.mkstemp(prefix=f"skill-{slug}-", suffix=".zip")
    Path(export_path).unlink(missing_ok=True)
    export_file = Path(export_path)
    try:
        with zipfile.ZipFile(export_file, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in skill_dir.rglob("*"):
                arcname = Path(slug) / p.relative_to(skill_dir)
                zf.write(p, arcname.as_posix())
    except Exception:
        export_file.unlink(missing_ok=True)
        raise
    return export_path, f"{slug}.zip"


async def delete_skill(db: AsyncSession, *, slug: str) -> None:
    repo = SkillRepository(db)
    item = await repo.get_by_slug(slug)
    if not item:
        raise ValueError(f"skill '{slug}' does not exist")

    skill_dir = _resolve_skill_dir(item)
    trash_dir: Path | None = None

    if skill_dir.exists():
        trash_dir = skill_dir.with_name(
            f".deleted-{slug}-{uuid.uuid4().hex[:8]}")
        skill_dir.rename(trash_dir)

    try:
        await repo.delete(item)
    except Exception:
        if trash_dir and trash_dir.exists():
            trash_dir.rename(skill_dir)
        raise

    if trash_dir and trash_dir.exists():
        shutil.rmtree(trash_dir, ignore_errors=True)


async def init_builtin_skills(db: AsyncSession, *, created_by: str = "system") -> None:
    """Validate built-in skill configuration without performing installation."""
    specs = get_builtin_skill_specs()

    for spec in specs:
        slug = str(getattr(spec, "slug", "")).strip()
        source_dir = Path(str(getattr(spec, "source_dir", ""))).resolve()

        if not is_valid_skill_slug(slug):
            raise ValueError(f"Invalid built-in skill slug: {slug}")
        if not source_dir.exists() or not source_dir.is_dir():
            logger.warning(
                f"Skipping missing built-in skill directory: {source_dir}")
            continue

        skill_md = source_dir / "SKILL.md"
        if not skill_md.exists():
            legacy_skill_md = source_dir / "SKILLS.md"
            if not legacy_skill_md.exists():
                raise ValueError(
                    f"Built-in skill is missing SKILL.md: {source_dir}")
            skill_md = legacy_skill_md

        content = skill_md.read_text(encoding="utf-8")
        parsed_name, _, meta = _parse_skill_markdown(content)
        if parsed_name != slug:
            raise ValueError(
                f"Built-in skill frontmatter.name must equal slug: {slug}")
        _normalize_string_list(meta.get("tool_dependencies"))
        _normalize_string_list(meta.get("mcp_dependencies"))
        _normalize_string_list(meta.get("skill_dependencies"))
        _compute_dir_hash(source_dir)


def list_builtin_skill_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for raw_spec in get_builtin_skill_specs():
        slug = str(getattr(raw_spec, "slug", "")).strip()
        source_dir = Path(str(getattr(raw_spec, "source_dir", ""))).resolve()
        configured_description = str(
            getattr(raw_spec, "description", "")).strip()
        version = str(getattr(raw_spec, "version", "1.0.0")).strip() or "1.0.0"
        configured_tools = _normalize_string_list(
            getattr(raw_spec, "tool_dependencies", None))
        configured_mcps = _normalize_string_list(
            getattr(raw_spec, "mcp_dependencies", None))
        configured_skills = _normalize_string_list(
            getattr(raw_spec, "skill_dependencies", None))

        if not is_valid_skill_slug(slug):
            raise ValueError(f"Invalid built-in skill slug: {slug}")
        if not source_dir.exists() or not source_dir.is_dir():
            logger.warning(
                f"Skipping missing built-in skill directory: {source_dir}")
            continue

        skill_md = source_dir / "SKILL.md"
        if not skill_md.exists():
            legacy_skill_md = source_dir / "SKILLS.md"
            if not legacy_skill_md.exists():
                raise ValueError(
                    f"Built-in skill is missing SKILL.md: {source_dir}")
            skill_md = legacy_skill_md

        content = skill_md.read_text(encoding="utf-8")
        parsed_name, parsed_desc, meta = _parse_skill_markdown(content)
        if parsed_name != slug:
            raise ValueError(
                f"Built-in skill frontmatter.name must equal slug: {slug}")

        specs.append(
            {
                "slug": slug,
                "name": slug,
                "description": configured_description or parsed_desc,
                "version": version,
                "tool_dependencies": configured_tools or _normalize_string_list(meta.get("tool_dependencies")),
                "mcp_dependencies": configured_mcps or _normalize_string_list(meta.get("mcp_dependencies")),
                "skill_dependencies": configured_skills or _normalize_string_list(meta.get("skill_dependencies")),
                "content_hash": _compute_dir_hash(source_dir),
                "source_dir": source_dir,
            }
        )

    return specs


async def install_builtin_skill(db: AsyncSession, slug: str, *, installed_by: str | None) -> Skill:
    _get_builtin_skill_spec_or_raise(slug)
    repo = SkillRepository(db)
    spec = next(item for item in list_builtin_skill_specs()
                if item["slug"] == slug)

    existing = await repo.get_by_slug(slug)
    if existing:
        raise ValueError(f"Built-in skill '{slug}' is already installed")

    target_dir = get_skills_root_dir() / slug
    if target_dir.exists():
        raise ValueError(f"skilldirectoryalready exists: {slug}")

    shutil.copytree(Path(spec["source_dir"]), target_dir, symlinks=False)
    try:
        return await repo.create(
            slug=slug,
            name=spec["name"],
            description=spec["description"],
            tool_dependencies=spec["tool_dependencies"],
            mcp_dependencies=spec["mcp_dependencies"],
            skill_dependencies=spec["skill_dependencies"],
            dir_path=_build_builtin_skill_dir_path(slug),
            version=spec["version"],
            is_builtin=True,
            content_hash=spec["content_hash"],
            created_by=installed_by or BUILTIN_SKILL_OPERATOR,
        )
    except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise


async def update_builtin_skill(
    db: AsyncSession,
    slug: str,
    *,
    force: bool = False,
    updated_by: str | None,
) -> Skill:
    _get_builtin_skill_spec_or_raise(slug)
    repo = SkillRepository(db)
    spec = next(item for item in list_builtin_skill_specs()
                if item["slug"] == slug)
    item = await repo.get_by_slug(slug)
    if not item:
        raise ValueError(f"Built-in skill '{slug}' is not installed")
    if not item.is_builtin and not _is_builtin_managed(item, slug):
        raise ValueError(f"skill '{slug}' is not a built-in skill")

    if item.content_hash != spec["content_hash"] and not force:
        raise BuiltinSkillUpdateConflictError(
            "Detected local modifications to this skill; updating will overwrite them. Continue?"
        )

    target_dir = _resolve_skill_dir(item)
    _replace_skill_target(target_dir, Path(spec["source_dir"]))

    if item.name != spec["name"] or item.description != spec["description"]:
        await repo.update_metadata(
            item,
            name=spec["name"],
            description=spec["description"],
            updated_by=updated_by,
        )

    if (
        _normalize_string_list(item.tool_dependencies or []
                               ) != spec["tool_dependencies"]
        or _normalize_string_list(item.mcp_dependencies or []) != spec["mcp_dependencies"]
        or _normalize_string_list(item.skill_dependencies or []) != spec["skill_dependencies"]
    ):
        await repo.update_dependencies(
            item,
            tool_dependencies=spec["tool_dependencies"],
            mcp_dependencies=spec["mcp_dependencies"],
            skill_dependencies=spec["skill_dependencies"],
            updated_by=updated_by,
        )

    return await repo.update_builtin_install(
        item,
        version=spec["version"],
        content_hash=spec["content_hash"],
        updated_by=updated_by,
    )
