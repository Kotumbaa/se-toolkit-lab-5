"""Router for analytics endpoints.

Each endpoint performs SQL aggregation queries on the interaction data
populated by the ETL pipeline. All endpoints require a `lab` query
parameter to filter results by lab (e.g., "lab-01").
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, case
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database import get_session
from app.models.item import ItemRecord
from app.models.learner import Learner
from app.models.interaction import InteractionLog

router = APIRouter()


@router.get("/scores")
async def get_scores(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    """Score distribution histogram for a given lab.

    - Find the lab item by matching title (e.g. "lab-04" → title contains "Lab 04")
    - Find all tasks that belong to this lab (parent_id = lab.id)
    - Query interactions for these items that have a score
    - Group scores into buckets: "0-25", "26-50", "51-75", "76-100"
      using CASE WHEN expressions
    - Return a JSON array:
      [{"bucket": "0-25", "count": 12}, {"bucket": "26-50", "count": 8}, ...]
    - Always return all four buckets, even if count is 0
    """
    # Find the lab item by title
    lab_title = f"Lab {lab.split('-')[1]}"
    lab_stmt = select(ItemRecord).where(
        ItemRecord.type == "lab",
        ItemRecord.title.contains(lab_title)
    )
    lab_result = await session.exec(lab_stmt)
    lab_item = lab_result.first()

    if not lab_item:
        return [
            {"bucket": "0-25", "count": 0},
            {"bucket": "26-50", "count": 0},
            {"bucket": "51-75", "count": 0},
            {"bucket": "76-100", "count": 0},
        ]

    # Find all tasks that belong to this lab
    tasks_stmt = select(ItemRecord.id).where(
        ItemRecord.type == "task",
        ItemRecord.parent_id == lab_item.id
    )
    tasks_result = await session.exec(tasks_stmt)
    task_ids = list(tasks_result.all())

    if not task_ids:
        return [
            {"bucket": "0-25", "count": 0},
            {"bucket": "26-50", "count": 0},
            {"bucket": "51-75", "count": 0},
            {"bucket": "76-100", "count": 0},
        ]

    # Query interactions for these items that have a score
    bucket_expr = case(
        (InteractionLog.score <= 25, "0-25"),
        (InteractionLog.score <= 50, "26-50"),
        (InteractionLog.score <= 75, "51-75"),
        (InteractionLog.score <= 100, "76-100"),
        else_="0-25",
    )

    stmt = (
        select(bucket_expr.label("bucket"), func.count().label("count"))
        .where(
            InteractionLog.item_id.in_(task_ids),
            InteractionLog.score.isnot(None)
        )
        .group_by("bucket")
    )

    result = await session.exec(stmt)
    counts = {row.bucket: row.count for row in result.all()}

    return [
        {"bucket": "0-25", "count": counts.get("0-25", 0)},
        {"bucket": "26-50", "count": counts.get("26-50", 0)},
        {"bucket": "51-75", "count": counts.get("51-75", 0)},
        {"bucket": "76-100", "count": counts.get("76-100", 0)},
    ]


@router.get("/pass-rates")
async def get_pass_rates(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    """Per-task pass rates for a given lab.

    - Find the lab item and its child task items
    - For each task, compute:
      - avg_score: average of interaction scores (round to 1 decimal)
      - attempts: total number of interactions
    - Return a JSON array:
      [{"task": "Repository Setup", "avg_score": 92.3, "attempts": 150}, ...]
    - Order by task title
    """
    # Find the lab item by title
    lab_title = f"Lab {lab.split('-')[1]}"
    lab_stmt = select(ItemRecord).where(
        ItemRecord.type == "lab",
        ItemRecord.title.contains(lab_title)
    )
    lab_result = await session.exec(lab_stmt)
    lab_item = lab_result.first()

    if not lab_item:
        return []

    # Find all tasks that belong to this lab
    tasks_stmt = select(ItemRecord).where(
        ItemRecord.type == "task",
        ItemRecord.parent_id == lab_item.id
    ).order_by(ItemRecord.title)
    tasks_result = await session.exec(tasks_stmt)
    tasks = list(tasks_result.all())

    result = []
    for task in tasks:
        # Get avg_score and attempts for this task
        stmt = (
            select(
                func.avg(InteractionLog.score).label("avg_score"),
                func.count().label("attempts")
            )
            .where(InteractionLog.item_id == task.id)
        )
        query_result = await session.exec(stmt)
        row = query_result.first()

        if row and row.attempts > 0:
            result.append({
                "task": task.title,
                "avg_score": round(row.avg_score, 1) if row.avg_score else 0.0,
                "attempts": row.attempts,
            })

    return result


@router.get("/timeline")
async def get_timeline(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    """Submissions per day for a given lab.

    - Find the lab item and its child task items
    - Group interactions by date (use func.date(created_at))
    - Count the number of submissions per day
    - Return a JSON array:
      [{"date": "2026-02-28", "submissions": 45}, ...]
    - Order by date ascending
    """
    # Find the lab item by title
    lab_title = f"Lab {lab.split('-')[1]}"
    lab_stmt = select(ItemRecord).where(
        ItemRecord.type == "lab",
        ItemRecord.title.contains(lab_title)
    )
    lab_result = await session.exec(lab_stmt)
    lab_item = lab_result.first()

    if not lab_item:
        return []

    # Find all tasks that belong to this lab
    tasks_stmt = select(ItemRecord.id).where(
        ItemRecord.type == "task",
        ItemRecord.parent_id == lab_item.id
    )
    tasks_result = await session.exec(tasks_stmt)
    task_ids = list(tasks_result.all())

    if not task_ids:
        return []

    # Group interactions by date
    stmt = (
        select(
            func.date(InteractionLog.created_at).label("date"),
            func.count().label("submissions")
        )
        .where(InteractionLog.item_id.in_(task_ids))
        .group_by("date")
        .order_by("date")
    )

    result = await session.exec(stmt)
    return [
        {"date": str(row.date), "submissions": row.submissions}
        for row in result.all()
    ]


@router.get("/groups")
async def get_groups(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    """Per-group performance for a given lab.

    - Find the lab item and its child task items
    - Join interactions with learners to get student_group
    - For each group, compute:
      - avg_score: average score (round to 1 decimal)
      - students: count of distinct learners
    - Return a JSON array:
      [{"group": "B23-CS-01", "avg_score": 78.5, "students": 25}, ...]
    - Order by group name
    """
    # Find the lab item by title
    lab_title = f"Lab {lab.split('-')[1]}"
    lab_stmt = select(ItemRecord).where(
        ItemRecord.type == "lab",
        ItemRecord.title.contains(lab_title)
    )
    lab_result = await session.exec(lab_stmt)
    lab_item = lab_result.first()

    if not lab_item:
        return []

    # Find all tasks that belong to this lab
    tasks_stmt = select(ItemRecord.id).where(
        ItemRecord.type == "task",
        ItemRecord.parent_id == lab_item.id
    )
    tasks_result = await session.exec(tasks_stmt)
    task_ids = list(tasks_result.all())

    if not task_ids:
        return []

    # Join interactions with learners and group by student_group
    stmt = (
        select(
            Learner.student_group.label("group"),
            func.avg(InteractionLog.score).label("avg_score"),
            func.count(func.distinct(Learner.id)).label("students")
        )
        .join(InteractionLog, Learner.id == InteractionLog.learner_id)
        .where(InteractionLog.item_id.in_(task_ids))
        .group_by(Learner.student_group)
        .order_by(Learner.student_group)
    )

    result = await session.exec(stmt)
    return [
        {
            "group": row.group,
            "avg_score": round(row.avg_score, 1) if row.avg_score else 0.0,
            "students": row.students,
        }
        for row in result.all()
    ]
