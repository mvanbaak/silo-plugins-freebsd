# Builder input index for the OFFICIAL FreeBSD catalog.
# Exactly one feed: the official Silo catalog. Community plugins never land here.
$official[0] as $o
| if ($o | type) != "object" then error("official feed must be a JSON object") else . end
| if ($o.plugins | type) != "array" then error("official plugins must be an array") else . end
| if ([$o.plugins[] | (type == "object" and (.manifest | type) == "object" and (.manifest.plugin_id | type) == "string" and (.repo_url | type) == "string")] | all) | not then error("malformed official plugin entry") else . end
| (["silo.tmdb", "silo.tvdb", "silo.theintrodb"]) as $required
| ([$o.plugins[].manifest.plugin_id]) as $ids
| if (($required - $ids) | length) != 0 then error("official feed missing default metadata plugins") else . end
| if ($ids | length) != ($ids | unique | length) then error("duplicate plugin id in official feed") else . end
| {plugins: $o.plugins}
