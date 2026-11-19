// Command silocatalog converts plugin manifests between the encodings Silo uses
// and verifies that a catalog index still decodes the way Silo decodes it.
//
//	normalize <manifest.json>  protojson -> encoding/json (enum names -> numbers)
//	check <index.json>         decode an index exactly as Silo does
package main

import (
	"encoding/json"
	"fmt"
	"os"

	pluginv1 "github.com/Silo-Server/silo-plugin-sdk/pkg/pluginproto/silo/plugin/v1"
	"google.golang.org/protobuf/encoding/protojson"
)

func main() {
	if len(os.Args) != 3 {
		fmt.Fprintln(os.Stderr, "usage: silocatalog <normalize|check> <file.json>")
		os.Exit(2)
	}
	var err error
	switch os.Args[1] {
	case "normalize":
		err = normalize(os.Args[2])
	case "check":
		err = check(os.Args[2])
	default:
		fmt.Fprintf(os.Stderr, "unknown subcommand %q\n", os.Args[1])
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

// normalize reads a plugin's own protojson manifest and writes the encoding/json
// form. Unknown fields are an error on purpose: a field this SDK does not know
// means the pin is older than the manifest, and silently dropping it would
// publish a catalog that lost data.
func normalize(path string) error {
	src, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	m := &pluginv1.PluginManifest{}
	if err := protojson.Unmarshal(src, m); err != nil {
		return err
	}
	out, err := json.Marshal(m)
	if err != nil {
		return err
	}
	_, err = os.Stdout.Write(append(out, '\n'))
	return err
}

// check decodes a catalog index the way Silo does: encoding/json into a struct
// whose manifest field is the protobuf message, so enum names are not accepted.
func check(path string) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	var idx struct {
		Plugins []struct {
			Manifest *pluginv1.PluginManifest `json:"manifest"`
		} `json:"plugins"`
	}
	if err := json.NewDecoder(f).Decode(&idx); err != nil {
		return err
	}
	fmt.Printf("%d entries\n", len(idx.Plugins))
	for _, p := range idx.Plugins {
		if p.Manifest == nil {
			return fmt.Errorf("entry without manifest")
		}
		fmt.Printf("%s %s\n", p.Manifest.GetPluginId(), p.Manifest.GetVersion())
	}
	return nil
}
