# Merge authoritative upstream catalogs into one index for the FreeBSD builder.
# Official entries are retained; only the approved community request plugins are included.
($official[0]) as $o
| ($community[0]) as $c
| if ($o | type) != "object" then error("official feed must be a JSON object") else . end
| if ($c | type) != "object" then error("community feed must be a JSON object") else . end
| if ($o.plugins | type) != "array" then error("official plugins must be an array") else . end
| if ($c.plugins | type) != "array" then error("community plugins must be an array") else . end
| if ([$o.plugins[] | (type == "object" and (.manifest | type) == "object" and (.manifest.plugin_id | type) == "string" and (.repo_url | type) == "string")] | all) | not then error("malformed official plugin entry") else . end
| if ([$c.plugins[] | (type == "object" and (.manifest | type) == "object" and (.manifest.plugin_id | type) == "string" and (.repo_url | type) == "string")] | all) | not then error("malformed community plugin entry") else . end
| (["silo.tmdb", "silo.tvdb", "silo.theintrodb"]) as $required
| ([$o.plugins[].manifest.plugin_id]) as $official_ids
| if (($required - $official_ids) | length) != 0 then error("official feed missing default metadata plugins") else . end
| (["silo.requests.arr", "silo.requests.seerr"]) as $approved
| ($c.plugins | map(select(.manifest.plugin_id as $id | $approved | index($id)))) as $selected
| (($o.plugins + $selected)) as $merged
| if ([$merged[].manifest.plugin_id] | length) != ([$merged[].manifest.plugin_id] | unique | length) then error("duplicate plugin id in merged catalog") else . end
| {plugins: $merged}