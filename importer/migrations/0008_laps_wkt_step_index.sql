-- The workout step each lap belongs to: the lap message's wkt_step_index
-- from the activity FIT file. It is the 0-based position of the step in the
-- workout the watch ran, in FIT order (a repeat group's steps come before
-- the repeat step itself). NULL when the run was not a structured workout.
-- One step can span several laps (auto lap every 1 km inside a 1.6 km rep),
-- and each repetition of a step gets its own laps.
--
-- Rows stored before this migration stay NULL until `runsync rebuild`.
ALTER TABLE laps ADD COLUMN wkt_step_index INTEGER;
