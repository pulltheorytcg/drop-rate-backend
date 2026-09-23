-- Keep founder membership records referentially tied to Supabase Auth users.
-- This also makes the Auth relationship visible to schema tooling/visualisers.
alter table tcg.owner_memberships
    add constraint owner_memberships_user_id_fkey
    foreign key (user_id)
    references auth.users(id)
    on delete cascade;
