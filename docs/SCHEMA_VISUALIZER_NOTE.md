# Schema visualizer note

The Drop Rate operational schema is `tcg`. Supabase Studio stores Schema Visualizer node positions in browser local storage; visual layout is therefore not controlled by database migrations. Database-side relationship integrity is represented with real foreign keys.

If the Studio layout is visually overlapped after schema changes, select the `tcg` schema and use Studio's automatic arrange control. New tables can initially overlap until arranged.
