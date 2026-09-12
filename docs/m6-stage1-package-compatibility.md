# M6–M5 Package Compatibility Contract

M6 preserves the v3.16.13 `story.zip` member layout, ordering, names and Stage
1 schemas established by M5. It does not add authority metadata, raw responses,
debug files, temporary files or quarantine evidence to the archive.

Every image member entering an M5-compatible package must first be represented
by an `ImageManifestEntry` reconstructed from exact content-addressed bytes and
must pass the M6 authority path: package quarantine, ownership, transaction and
generation-call provenance, current PASS gate, mutation status and delivery
status. A caller that cannot provide this authority record must fail closed;
there is no legacy image fallback.

Non-image Stage 1 members continue to use the M5 deterministic validators.
This compatibility boundary avoids changing the canonical archive schema while
preventing an image response from bypassing M6 authority checks. M6 package
publication remains incomplete until the Stage 1 orchestrator supplies the
persisted authority records for every image member.
