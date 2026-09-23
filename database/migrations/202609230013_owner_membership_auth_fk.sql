begin;

-- Tie founder membership records to Supabase Auth so referential integrity is
-- enforced and schema tooling can display the real relationship.
do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'owner_memberships_user_id_fkey'
          and conrelid = 'tcg.owner_memberships'::regclass
    ) then
        alter table tcg.owner_memberships
            add constraint owner_memberships_user_id_fkey
            foreign key (user_id)
            references auth.users(id)
            on delete cascade;
    end if;
end
$$;

commit;
