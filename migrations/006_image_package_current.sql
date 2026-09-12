CREATE UNIQUE INDEX image_packages_one_successor_idx
ON image_packages(supersedes_id)
WHERE supersedes_id IS NOT NULL;
