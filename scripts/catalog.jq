# Builder input index for the FreeBSD catalog: the plugins listed in
# scripts/plugins.txt, one per repository.
(($ARGS.named.extra // [])[0] // {plugins: []}) as $e
| if ($e | type) != "object" then error("extras input must be a JSON object") else . end
| if ($e.plugins | type) != "array" then error("extras plugins must be an array") else . end
| if ([$e.plugins[] | (type == "object" and (.manifest | type) == "object" and (.manifest.plugin_id | type) == "string" and (.repo_url | type) == "string")] | all) | not then error("malformed extras plugin entry") else . end
| ([$e.plugins[].manifest.plugin_id]) as $ids
| if ($ids | length) != ($ids | unique | length) then error("duplicate plugin id in extras") else . end
| {plugins: $e.plugins}
