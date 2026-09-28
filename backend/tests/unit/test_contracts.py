from copy import deepcopy

import pytest

from shield_api.config import compile_config
from shield_api.contracts import ConfigInvalid, Registry


REGISTRY = Registry.model_validate(
    {
        "upstreams": [
            {"id": "demo-origin", "name": "Demo", "scheme": "http", "host": "127.0.0.1", "port": 9000}
        ]
    }
)


def config_doc():
    return {
        "schema_version": 1,
        "service": {
            "id": "demo",
            "name": "Demo",
            "public_host": "api.localhost",
            "upstream_id": "demo-origin",
            "enabled": True,
            "unmatched_action": "baseline",
            "max_body_bytes": 1024,
            "ip_rate": {"limit": 3, "window_seconds": 60},
            "abuse": {},
            "routes": [
                {
                    "id": "cart",
                    "name": "Cart",
                    "path": "/cart",
                    "methods": ["POST"],
                    "max_body_bytes": 512,
                    "content_types": ["application/json"],
                    "ip_rate": None,
                    "json_schema": {
                        "type": "object",
                        "properties": {"quantity": {"type": "integer", "minimum": 1}},
                        "required": ["quantity"],
                        "additionalProperties": False,
                    },
                }
            ],
        },
    }


def test_json_arrays_validate_strictly():
    compiled = compile_config(config_doc(), REGISTRY)
    assert compiled.routes[0].route.methods == ("POST",)
    assert compiled.document.service.abuse.auto_ban_enabled is False
    with pytest.raises(TypeError):
        compiled.routes[0].route.json_schema["type"] = "array"


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["service"].update(enabled=1),
        lambda d: d["service"].update(unmatched_action="allow"),
        lambda d: d["service"].update(unknown=True),
        lambda d: d["service"]["routes"][0].update(max_body_bytes=2000),
        lambda d: d["service"]["routes"][0]["json_schema"].update(**{"$ref": "https://example.org/schema"}),
        lambda d: d["service"]["routes"].append(deepcopy(d["service"]["routes"][0])),
    ],
)
def test_invalid_config_rejected(change):
    document = config_doc()
    change(document)
    with pytest.raises(ConfigInvalid):
        compile_config(document, REGISTRY)


def test_ambiguous_intersection_and_specificity():
    document = config_doc()
    routes = document["service"]["routes"]
    routes[0]["path"] = "/a/{x}/c"
    other = deepcopy(routes[0])
    other.update(id="other", path="/a/b/{y}")
    routes.append(other)
    with pytest.raises(ConfigInvalid, match="ambiguous"):
        compile_config(document, REGISTRY)
    other["path"] = "/a/b/c"
    assert len(compile_config(document, REGISTRY).routes) == 2


def test_trailing_slash_is_distinct():
    document = config_doc()
    other = deepcopy(document["service"]["routes"][0])
    other.update(id="cart-slash", path="/cart/")
    document["service"]["routes"].append(other)
    assert len(compile_config(document, REGISTRY).routes) == 2
