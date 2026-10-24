"""Jobs track the pipeline stage; a ready card waits in the queue instead of being completed.

A job whose card was handed to parameter selection was "completed" with next_stage
"queued". It is now "queued" at the "parameters" stage, so its waiting task runs it.
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        UPDATE jobs SET payload = (payload - 'next_stage') || CASE
            WHEN payload->>'next_stage' = 'queued' AND payload->>'status' = 'completed'
                THEN '{"stage": "parameters", "status": "queued"}'::jsonb
            ELSE '{"stage": "understanding"}'::jsonb
        END
        WHERE payload ? 'next_stage'
        """
    )


def downgrade():
    op.execute(
        """
        UPDATE jobs SET payload = (payload - 'stage' - 'parameters') || CASE
            WHEN payload->>'stage' IN ('parameters', 'validation', 'done')
                THEN '{"next_stage": "queued", "status": "completed"}'::jsonb
            ELSE '{"next_stage": "not_ready"}'::jsonb
        END
        WHERE payload ? 'stage'
        """
    )
