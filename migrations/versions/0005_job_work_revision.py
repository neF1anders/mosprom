"""Jobs keep the revision of their work and the outcome of a finished pipeline.

A reply in the chat that starts no work opens a revision of its own, so the card, the
timeline and the results are found by ``work_revision``. Every job's work so far is its
current revision. ``outcome`` is what the chat shows for a finished pipeline. The fields
nothing writes any more go: ``phase``, ``units`` and the card's ``verdict``.
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        UPDATE jobs SET payload = (payload - 'phase' - 'units')
            || jsonb_build_object('work_revision', payload->'revision')
            || CASE
                WHEN payload->>'status' <> 'completed' THEN '{}'::jsonb
                WHEN payload->'parameters'->>'check' = 'attention'
                    THEN '{"outcome": "parameters_attention"}'::jsonb
                WHEN jsonb_typeof(payload->'result') IS DISTINCT FROM 'object' THEN '{}'::jsonb
                WHEN payload->'result'->>'sliced' <> 'true'
                    THEN '{"outcome": "not_sliced"}'::jsonb
                WHEN payload->'result'->>'gcode_check' = 'ok' THEN '{"outcome": "ready"}'::jsonb
                ELSE '{"outcome": "attention"}'::jsonb
            END
        """
    )
    op.execute(
        """
        UPDATE jobs SET payload = jsonb_set(payload, '{card}', (payload->'card') - 'verdict')
        WHERE jsonb_typeof(payload->'card') = 'object'
        """
    )


def downgrade():
    op.execute("UPDATE jobs SET payload = payload - 'work_revision' - 'outcome'")
