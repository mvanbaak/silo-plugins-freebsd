# Builder input index for the COMMUNITY FreeBSD catalog.
# Every plugin in the community feed is mirrored; the feed itself is the allowlist.
# An optional second input (--slurpfile extra) appends plugins that are not in
# that feed, one per repository listed in scripts/community-extra.txt.
(($ARGS.named.extra // [])[0] // {plugins: []}) as $e
| $community[0] as $c
| if ($c | type) != "object" then error("community feed must be a JSON object") else . end
| if ($c.plugins | type) != "array" then error("community plugins must be an array") else . end
| if ($e | type) != "object" then error("community extra input must be a JSON object") else . end
| if ($e.plugins | type) != "array" then error("community extra plugins must be an array") else . end
| if ([$c.plugins[] | (type == "object" and (.manifest | type) == "object" and (.manifest.plugin_id | type) == "string" and (.repo_url | type) == "string")] | all) | not then error("malformed community plugin entry") else . end
| if ([$e.plugins[] | (type == "object" and (.manifest | type) == "object" and (.manifest.plugin_id | type) == "string" and (.repo_url | type) == "string")] | all) | not then error("malformed community extra plugin entry") else . end
| ([$c.plugins[].manifest.plugin_id]) as $ids
| if ($ids | length) != ($ids | unique | length) then error("duplicate plugin id in community feed") else . end
| ([$e.plugins[].manifest.plugin_id]) as $extra_ids
| if ($extra_ids | length) != ($extra_ids | unique | length) then error("duplicate plugin id in community extras") else . end
| if ([$ids[] | select(. as $id | $extra_ids | index($id))] | length) != 0 then error("duplicate plugin id in community feed and extras") else . end
| {plugins: ($c.plugins + $e.plugins)}
