from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def _json_type() -> sa.types.TypeEngine:
    dialect_name = op.get_bind().dialect.name
    if dialect_name == "postgresql":
        return postgresql.JSONB(astext_type=sa.Text())
    return sa.JSON()


def _uuid_type() -> sa.types.TypeEngine:
    return sa.Uuid()


def _timestamp_type() -> sa.types.TypeEngine:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    json_type = _json_type()
    uuid_type = _uuid_type()
    timestamp_type = _timestamp_type()

    op.create_table(
        "pl_plans",
        sa.Column("plan_id", uuid_type, primary_key=True, nullable=False),
        sa.Column("request_id", uuid_type, nullable=False),
        sa.Column("intent", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("snapshot", json_type, nullable=False),
        sa.Column("created_at", timestamp_type, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", timestamp_type, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_pl_plans_request", "pl_plans", ["request_id"])
    op.create_index("ix_pl_plans_status", "pl_plans", ["status"])

    op.create_table(
        "pl_subtasks",
        sa.Column("subtask_id", uuid_type, primary_key=True, nullable=False),
        sa.Column(
            "plan_id",
            uuid_type,
            sa.ForeignKey("pl_plans.plan_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("spec", json_type, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", timestamp_type, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", timestamp_type, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_pl_subtasks_plan_status", "pl_subtasks", ["plan_id", "status"])

    op.create_table(
        "pl_failure_signals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("plan_id", uuid_type, nullable=False),
        sa.Column("subtask_id", uuid_type, nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("payload", json_type, nullable=False),
        sa.Column("occurred_at", timestamp_type, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_pl_failure_signals_plan", "pl_failure_signals", ["plan_id"])

    op.create_table(
        "cl_runs",
        sa.Column("run_id", uuid_type, primary_key=True, nullable=False),
        sa.Column("plan_id", uuid_type, nullable=False),
        sa.Column("subtask_id", uuid_type, nullable=False),
        sa.Column("thread_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total_urls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metrics", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("artifacts_dir", sa.Text(), nullable=False, server_default=""),
        sa.Column("started_at", timestamp_type, nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", timestamp_type, nullable=True),
        sa.Column("created_at", timestamp_type, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", timestamp_type, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_cl_runs_plan", "cl_runs", ["plan_id"])
    op.create_index("ix_cl_runs_subtask", "cl_runs", ["subtask_id"])
    op.create_index("ix_cl_runs_status", "cl_runs", ["status"])

    op.create_table(
        "cl_page_results",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            uuid_type,
            sa.ForeignKey("cl_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fields", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error_kind", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", timestamp_type, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("run_id", "url", name="uq_cl_page_results_run_url"),
    )
    op.create_index("ix_cl_page_results_status", "cl_page_results", ["run_id", "status"])

    op.create_table(
        "cl_field_xpaths",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("field_name", sa.String(length=128), nullable=False),
        sa.Column("xpath", sa.Text(), nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_success_at", timestamp_type, nullable=True),
        sa.Column("last_failure_at", timestamp_type, nullable=True),
        sa.Column("created_at", timestamp_type, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", timestamp_type, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("domain", "field_name", "xpath", name="uq_cl_field_xpaths_identity"),
    )

    op.create_table(
        "ex_skills",
        sa.Column("skill_id", uuid_type, primary_key=True, nullable=False),
        sa.Column("site_host", sa.String(length=255), nullable=False),
        sa.Column("intent_key", sa.String(length=128), nullable=False),
        sa.Column("definition", json_type, nullable=False),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", timestamp_type, nullable=True),
        sa.Column("created_at", timestamp_type, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", timestamp_type, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ex_skills_host_intent", "ex_skills", ["site_host", "intent_key"], unique=True)

    op.create_table(
        "ex_skill_usages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "skill_id",
            uuid_type,
            sa.ForeignKey("ex_skills.skill_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_id", uuid_type, nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("metrics", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("recorded_at", timestamp_type, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ex_usages_skill", "ex_skill_usages", ["skill_id", "recorded_at"])

    op.create_table(
        "ch_sessions",
        sa.Column("session_id", uuid_type, primary_key=True, nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("turns", json_type, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("clarified", json_type, nullable=True),
        sa.Column("created_at", timestamp_type, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", timestamp_type, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ch_sessions_status", "ch_sessions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_ch_sessions_status", table_name="ch_sessions")
    op.drop_table("ch_sessions")
    op.drop_index("ix_ex_usages_skill", table_name="ex_skill_usages")
    op.drop_table("ex_skill_usages")
    op.drop_index("ix_ex_skills_host_intent", table_name="ex_skills")
    op.drop_table("ex_skills")
    op.drop_table("cl_field_xpaths")
    op.drop_index("ix_cl_page_results_status", table_name="cl_page_results")
    op.drop_table("cl_page_results")
    op.drop_index("ix_cl_runs_status", table_name="cl_runs")
    op.drop_index("ix_cl_runs_subtask", table_name="cl_runs")
    op.drop_index("ix_cl_runs_plan", table_name="cl_runs")
    op.drop_table("cl_runs")
    op.drop_index("ix_pl_failure_signals_plan", table_name="pl_failure_signals")
    op.drop_table("pl_failure_signals")
    op.drop_index("ix_pl_subtasks_plan_status", table_name="pl_subtasks")
    op.drop_table("pl_subtasks")
    op.drop_index("ix_pl_plans_status", table_name="pl_plans")
    op.drop_index("ix_pl_plans_request", table_name="pl_plans")
    op.drop_table("pl_plans")
