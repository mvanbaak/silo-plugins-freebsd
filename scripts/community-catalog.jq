# Builder input index for the COMMUNITY FreeBSD catalog.
# Every plugin in the community feed is mirrored; the feed itself is the allowlist.
$community[0] as $c
| if ($c | type) != "object" then error("community feed must be a JSON object") else . end
| if ($c.plugins | type) != "array" then error("community plugins must be an array") else . end
| if ([$c.plugins[] | (type == "object" and (.manifest | type) == "object" and (.manifest.plugin_id | type) == "string" and (.repo_url | type) == "string")] | all) | not then error("malformed community plugin entry") else . end
| ([$c.plugins[].manifest.plugin_id]) as $ids
| if ($ids | length) != ($ids | unique | length) then error("duplicate plugin id in community feed") else . end
| {plugins: $c.plugins}
