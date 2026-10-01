begin;

-- Forward-only hardening for Competitive Intelligence opportunity replay.
-- The base persistence migration is already applied in production, so this
-- migration records the exact qualification threshold used for each opportunity.

alter table tcg.competitive_opportunities
    add column qualification_threshold numeric(6,5) not null default 0.72
        check (qualification_threshold between 0 and 1);

commit;
