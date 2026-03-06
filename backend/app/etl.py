"""ETL pipeline: fetch data from the autochecker API and load it into the database.

The autochecker dashboard API provides two endpoints:
- GET /api/items — lab/task catalog
- GET /api/logs  — anonymized check results (supports ?since= and ?limit= params)

Both require HTTP Basic Auth (email + password from settings).
"""

from datetime import datetime

import httpx
from sqlalchemy import desc
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.settings import settings


# ---------------------------------------------------------------------------
# Extract — fetch data from the autochecker API
# ---------------------------------------------------------------------------


async def fetch_items() -> list[dict]:
    """Fetch the lab/task catalog from the autochecker API.

    Uses HTTP Basic Auth with credentials from settings.
    Returns a list of item dicts with keys: lab, task, title, type.
    Raises an exception if the response status is not 200.
    """
    url = f"{settings.autochecker_api_url}/api/items"
    auth = (settings.autochecker_email, settings.autochecker_password)

    async with httpx.AsyncClient() as client:
        response = await client.get(url, auth=auth)
        response.raise_for_status()
        return response.json()


async def fetch_logs(since: datetime | None = None) -> list[dict]:
    """Fetch check results from the autochecker API.

    Uses HTTP Basic Auth with credentials from settings.
    Fetches in batches of 500 with pagination.
    Returns the combined list of all log dicts from all pages.
    """
    url = f"{settings.autochecker_api_url}/api/logs"
    auth = (settings.autochecker_email, settings.autochecker_password)
    all_logs: list[dict] = []
    current_since = since

    async with httpx.AsyncClient() as client:
        while True:
            params: dict[str, str | int] = {"limit": 500}
            if current_since is not None:
                params["since"] = current_since.isoformat()

            response = await client.get(url, auth=auth, params=params)
            response.raise_for_status()
            data = response.json()

            logs = data.get("logs", [])
            all_logs.extend(logs)

            if not data.get("has_more", False):
                break

            # Use the submitted_at of the last log as the new since
            current_since = datetime.fromisoformat(logs[-1]["submitted_at"])

    return all_logs


# ---------------------------------------------------------------------------
# Load — insert fetched data into the local database
# ---------------------------------------------------------------------------


async def load_items(items: list[dict], session: AsyncSession) -> int:
    """Load items (labs and tasks) into the database.

    Processes labs first, then tasks. Checks for duplicates before inserting.
    Returns the number of newly created items.
    """
    from app.models.item import ItemRecord

    new_items_count = 0
    lab_id_map: dict[str, ItemRecord] = {}

    # Process labs first (items where type="lab")
    labs = [item for item in items if item.get("type") == "lab"]
    for lab in labs:
        lab_title = lab["title"]
        # Check if lab already exists
        existing_lab = await session.execute(
            select(ItemRecord).where(
                ItemRecord.type == "lab",
                ItemRecord.title == lab_title,
            )
        )
        lab_record = existing_lab.scalar_one_or_none()

        if lab_record is None:
            lab_record = ItemRecord(type="lab", title=lab_title)
            session.add(lab_record)
            new_items_count += 1

        # Map short lab ID (e.g., "lab-01") to the record
        lab_short_id = lab["lab"]
        lab_id_map[lab_short_id] = lab_record

    # Process tasks (items where type="task")
    tasks = [item for item in items if item.get("type") == "task"]
    for task in tasks:
        task_title = task["title"]
        lab_short_id = task["lab"]

        # Find parent lab
        parent_lab = lab_id_map.get(lab_short_id)
        if parent_lab is None:
            # Parent lab not found, skip this task
            continue

        # Check if task already exists with this title and parent_id
        existing_task = await session.execute(
            select(ItemRecord).where(
                ItemRecord.type == "task",
                ItemRecord.title == task_title,
                ItemRecord.parent_id == parent_lab.id,
            )
        )
        task_record = existing_task.scalar_one_or_none()

        if task_record is None:
            task_record = ItemRecord(
                type="task",
                title=task_title,
                parent_id=parent_lab.id,
            )
            session.add(task_record)
            new_items_count += 1

    await session.commit()
    return new_items_count


async def load_logs(
    logs: list[dict], items_catalog: list[dict], session: AsyncSession
) -> int:
    """Load interaction logs into the database.

    Args:
        logs: Raw log dicts from the API (each has lab, task, student_id, etc.)
        items_catalog: Raw item dicts from fetch_items() — needed to map
            short IDs (e.g. "lab-01", "setup") to item titles stored in the DB.
        session: Database session.

    Returns the number of newly created interactions.
    """
    from app.models.interaction import InteractionLog
    from app.models.item import ItemRecord
    from app.models.learner import Learner

    # Build lookup: (lab_short_id, task_short_id) -> title
    item_title_lookup: dict[tuple[str, str | None], str] = {}
    for item in items_catalog:
        lab_short_id = item["lab"]
        task_short_id = item.get("task")  # None for labs
        title = item["title"]
        item_title_lookup[(lab_short_id, task_short_id)] = title

    new_interactions_count = 0

    for log in logs:
        # 1. Find or create Learner
        student_id = log["student_id"]
        learner = await session.execute(
            select(Learner).where(Learner.external_id == student_id)
        )
        learner_record = learner.scalar_one_or_none()

        if learner_record is None:
            learner_record = Learner(
                external_id=student_id,
                student_group=log.get("group", ""),
            )
            session.add(learner_record)
            await session.flush()  # Get the ID

        # 2. Find the matching item
        lab_short_id = log["lab"]
        task_short_id = log.get("task")  # May be None for lab-level logs
        item_title = item_title_lookup.get((lab_short_id, task_short_id))

        if item_title is None:
            # No matching item found, skip this log
            continue

        # Determine item type based on whether task_short_id is present
        item_type = "task" if task_short_id is not None else "lab"

        item_record = await session.execute(
            select(ItemRecord)
            .where(
                ItemRecord.title == item_title,
                ItemRecord.type == item_type,
            )
            .limit(1)
        )
        item = item_record.scalar_one_or_none()

        if item is None:
            # Item not in DB yet, skip this log
            continue

        # 3. Check for existing InteractionLog (idempotent upsert)
        log_external_id = log["id"]
        existing_interaction = await session.execute(
            select(InteractionLog).where(
                InteractionLog.external_id == log_external_id
            )
        )
        if existing_interaction.scalar_one_or_none() is not None:
            # Already exists, skip
            continue

        # 4. Create InteractionLog
        interaction = InteractionLog(
            external_id=log_external_id,
            learner_id=learner_record.id,
            item_id=item.id,
            kind="attempt",
            score=log.get("score"),
            checks_passed=log.get("passed"),
            checks_total=log.get("total"),
            created_at=datetime.fromisoformat(log["submitted_at"]),
        )
        session.add(interaction)
        new_interactions_count += 1

    await session.commit()
    return new_interactions_count


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def sync(session: AsyncSession) -> dict:
    """Run the full ETL pipeline.

    Fetches items and logs from the autochecker API and loads them
    into the local database. Returns a summary of the sync operation.
    """
    from app.models.interaction import InteractionLog

    # Step 1: Fetch items and load them into the database
    items = await fetch_items()
    await load_items(items, session)

    # Step 2: Determine the last synced timestamp
    latest_log = await session.execute(
        select(InteractionLog)
        .order_by(desc(InteractionLog.created_at))
        .limit(1)
    )
    latest_record = latest_log.scalar_one_or_none()
    since = latest_record.created_at if latest_record else None

    # Step 3: Fetch logs since that timestamp and load them
    logs = await fetch_logs(since=since)
    new_records = await load_logs(logs, items, session)

    # Get total records count
    total_result = await session.execute(
        select(InteractionLog).where(InteractionLog.id.isnot(None))
    )
    total_records = len(total_result.scalars().all())

    return {
        "new_records": new_records,
        "total_records": total_records,
    }
