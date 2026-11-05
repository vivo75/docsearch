"""azurerm extractor: parsing of a tiny provider tree (no network, no real provider source)."""
import json
import textwrap

import pytest

from docsearch import azurerm_extract as A

REGISTRATION = '''package demo

func (Registration) SupportedResources() map[string]*pluginsdk.Resource {
	return map[string]*pluginsdk.Resource{
		"azurerm_demo_thing": resourceDemoThing(),
	}
}
'''

RESOURCE = '''package demo

func resourceDemoThing() *pluginsdk.Resource {
	return &pluginsdk.Resource{
		Create: resourceDemoThingCreate,
		Read:   resourceDemoThingRead,
		Schema: map[string]*pluginsdk.Schema{
			"name": {
				Type:         pluginsdk.TypeString,
				Required:     true,
				ForceNew:     true,
				ValidateFunc: validation.StringIsNotEmpty,
			},
			"location": commonschema.Location(),
			"mode": {
				Type:         pluginsdk.TypeString,
				Optional:     true,
				Default:      "Fast",
				ValidateFunc: validation.StringInSlice([]string{"Fast", "Slow"}, false),
				ConflictsWith: []string{"other"},
			},
			"other": {Type: pluginsdk.TypeString, Optional: true},
			"retention_days": {
				Type:         pluginsdk.TypeInt,
				Optional:     true,
				Default:      7,
				ValidateFunc: validation.IntBetween(1, 35),
			},
			"settings": {
				Type:     pluginsdk.TypeList,
				Optional: true,
				MaxItems: 1,
				Elem: &pluginsdk.Resource{
					Schema: map[string]*pluginsdk.Schema{
						"level": {Type: pluginsdk.TypeInt, Required: true, ValidateFunc: validation.IntAtLeast(0)},
					},
				},
			},
		},
	}
}

func resourceDemoThingCreate(d *pluginsdk.ResourceData, meta interface{}) error {
	if d.HasChange("mode") {
		x := expandDemoMode(d.Get("mode").(string))
		_ = x
	}
	return nil
}

func resourceDemoThingRead(d *pluginsdk.ResourceData, meta interface{}) error {
	return nil
}

func expandDemoMode(s string) string { return s }
'''


@pytest.fixture()
def provider(tmp_path, monkeypatch):
    svc = tmp_path / "internal" / "services" / "demo"
    svc.mkdir(parents=True)
    (svc / "registration.go").write_text(REGISTRATION)
    (svc / "demo_thing_resource.go").write_text(RESOURCE)
    (tmp_path / "go.mod").write_text("module x\nrequire github.com/hashicorp/go-azure-sdk/resource-manager v0.1.0\n")
    (tmp_path / "LICENSE").write_text("Mozilla Public License Version 2.0\n")
    monkeypatch.setattr(A, "PROVIDER", tmp_path)
    monkeypatch.setattr(A, "CACHE", tmp_path / "cache")
    (tmp_path / "cache" / "v0.1.0").mkdir(parents=True)
    (tmp_path / "cache" / "v0.1.0" / "LICENSE").write_text("Mozilla Public License Version 2.0\n")
    A._SRC_CACHE.clear(); A._DIR_FUNCS.clear(); A._cache.clear()
    return tmp_path


def test_schema_facts(provider):
    r = A.extract("azurerm_demo_thing")
    a = r["arguments"]
    assert a["name"]["required"] and a["name"]["force_new"] and a["name"]["type"] == "string"
    assert a["mode"]["default"] == "Fast" and a["mode"]["validate"] == {"kind": "enum", "values": ["Fast", "Slow"], "case_sensitive": True}
    assert a["mode"]["conflicts_with"] == ["other"]
    assert a["retention_days"]["validate"] == {"kind": "int_range", "min": 1, "max": 35}
    assert a["location"]["type"] == "string" and a["location"]["required"]         # shared helper known by name
    blk = a["settings"]["block"]["level"]
    assert blk["required"] and blk["validate"]["kind"] == "intatleast"
    assert r["provenance"]["provider"]["license"] == "MPL-2.0"


def test_flow_and_no_source_text(provider):
    r = A.extract("azurerm_demo_thing")
    assert "expandDemoMode()" in r["crud"]["create"]["mermaid"]
    blob = json.dumps(r)
    assert "func " not in blob and "return nil" not in blob                         # derived facts only


def test_describe_sections(provider):
    s = A.describe("azurerm_demo_thing")
    assert s["counts"]["required"] == ["location", "name"] and s["counts"]["blocks"] == ["settings"]
    c = A.describe("azurerm_demo_thing", section="arguments")
    assert c["arguments"]["settings"]["block_arguments"] == ["level"] and "block" not in c["arguments"]["settings"]
    d = A.describe("azurerm_demo_thing", section="arguments", argument="settings.level")
    assert d["detail"]["required"]
    assert "error" in A.describe("azurerm_demo_thing", section="flow")             # operation missing
    assert "flowchart" in A.describe("azurerm_demo_thing", section="flow", operation="create")["diagram"]
    assert "error" in A.describe("../etc/passwd") and "error" in A.describe("azurerm_unknown_thing")
